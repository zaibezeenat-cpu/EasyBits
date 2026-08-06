    for domain, candidates in by_domain.items():
        # THE MAIN STOP. An official source plus one cross-check already confirms
        # everything that is ever going to be confirmed, so the rest of the list
        # cannot change a single output -- it can only cost time. On the measured
        # run this fires at ~9s instead of running to the attempt ceiling at 137s.
        if _corroboration_satisfied(scraped_data):
            logger.info(
                f"Corroboration satisfied for {brand_name} {model_number} with "
                f"{len(scraped_data)} source(s) including an official one after "
                f"{attempted} attempt(s); further sources cannot change the result."
            )
            break

        # Diminishing returns. Covers the case the rule above cannot: a product
        # with no official source available, where the old code would still walk
        # the entire configured list one dead domain at a time.
        if consecutive_empty_domains >= MAX_CONSECUTIVE_EMPTY_DOMAINS:
            logger.info(
                f"{consecutive_empty_domains} consecutive domains yielded nothing for "
                f"{brand_name} {model_number}; stopping with {len(scraped_data)} source(s) "
                f"rather than walking the remaining {len(by_domain) - attempted} domain(s)."
            )
            break

        # Stop once enough independent sources are in hand. With 20+ configured
        # retailers, scraping every one would take many minutes per product;
        # corroboration only needs a handful of agreeing sources, and domains are
        # tried in trust order (official, then trusted, then web), so the first
        # few are the most authoritative.
        if len(scraped_data) >= MAX_SOURCES_FOR_CORROBORATION:
            logger.info(
                f"Collected {len(scraped_data)} sources for {brand_name} {model_number}; "
                f"stopping early (cap {MAX_SOURCES_FOR_CORROBORATION})."
            )
            break
        if attempted >= MAX_SCRAPE_ATTEMPTS:
            logger.info(
                f"Reached the {MAX_SCRAPE_ATTEMPTS}-attempt ceiling for {brand_name} "
                f"{model_number} with {len(scraped_data)} source(s); stopping to bound time."
            )
            break
        sources_before_domain = len(scraped_data)
        for source in candidates:
            attempted += 1
            try:
                result = await smart_fetch(source["url"], model_number)
            except Exception as e:
                logger.warning(f"Scrape failed for {source['url']}: {e}")
                continue

            if not result.success or not result.content:
                continue

            # An anti-bot challenge loads with content but is not the product. Flag
            # it as a block (not a no-match) so the escalation is actionable.
            if is_block_page(result.content):
                blocked = True
                logger.warning(
                    f"{source['url']} returned an anti-bot/block page (Cloudflare etc.); "
                    f"skipping. Operator can paste Details to bypass."
                )
                continue

            if not search_result_mentions_product(result.content, model_number):
                # Domain bail-out: if the search page loaded successfully AND
                # mentions the brand name (proof the search engine is working on
                # this domain, not just returning an error/empty page), but does
                # NOT mention our model number, this domain has confirmed it does
                # not stock this product. Skip all remaining URL patterns for it.
                #
                # WHY THIS IS SAFE: we only bail when the brand appears in content,
                # ruling out the case where a pattern returned the wrong platform's
                # "no results" page (which would not mention the brand at all).
                # This preserves the original multi-pattern logic for all cases
                # where the search page is genuinely empty or wrong-platform.
                # Use only the FIRST alphanumeric token of the brand name for
                # the content check. Splitting on any separator (space, hyphen,
                # underscore) handles all real-world brand name formats:
                #   "WestPoint Pakistan" -> "WestPoint"
                #   "WestPoint-Pakistan" -> "WestPoint"
                #   "Kenwood"            -> "Kenwood"
                brand_token = re.split(r"[^a-zA-Z0-9]", brand_name)[0] if brand_name else brand_name
                if search_result_mentions_product(result.content, brand_token):
                    logger.info(
                        f"Domain {domain} confirmed: search works (mentions '{brand_name}') "
                        f"but '{model_number}' is not stocked there. "
                        f"Skipping {len(candidates) - candidates.index(source) - 1} "
                        f"remaining URL pattern(s) for this domain."
                    )
                    break  # skip remaining candidates for this domain
                logger.debug(
                    f"{source['url']} loaded but does not mention {model_number}; "
                    f"treating as no-match"
                )
                continue

            # A Google/web result IS already a product detail page, not a search
            # listing, so it is used directly once it names the model -- there is
            # no further page to follow to. For a `web` (unvetted) source, brand
            # identity is still required so a wrong-product page cannot slip in.
            if source.get("is_direct") == "true":
                # A direct product page must identify as this exact model (title/
                # slug), guarding the IPRA/IPGA suffix trap on web results too.
                if not model_matches_identity(model_number, result.url or source["url"],
                                              result.candidate_titles):
                    logger.info(
                        f"Rejected direct result {source['url']}: title/URL is a different "
                        f"model variant than {model_number}."
                    )
                    continue
                if (source["source_type"] == "web"
                        and not brand_matches_identity(brand_name, result.url or source["url"],
                                                       result.candidate_titles)):
                    logger.info(
                        f"Rejected direct web result {source['url']}: names {model_number} "
                        f"but does not identify as '{brand_name}'."
                    )
                    continue
                detail = result
            else:
                # A search hit is only a lead. The detail page is the evidence --
                # see _follow_to_detail_page for why a listing alone is rejected.
                detail = await _follow_to_detail_page(
                    result,
                    model_number,
                    brand_name=brand_name,
                    # A path scope is recorded only for hosts that serve more than
                    # one brand, so its presence is exactly the condition under
                    # which brand identity has to be proven.
                    require_brand_identity=bool(source.get("scope_path")),
                )
            if detail is None:
                logger.info(
                    f"{source['url']} matched the query but no product page for "
                    f"{model_number} was found on {domain}; discarding this source"
                )
                brand_token = re.split(r"[^a-zA-Z0-9]", brand_name)[0] if brand_name else brand_name
                if result.content and search_result_mentions_product(result.content, brand_token):
                    logger.info(
                        f"Search page on {domain} confirmed working (mentions '{brand_token}') "
                        f"but '{model_number}' detail page not found. Bailing out of remaining candidate patterns."
                    )
                    break
                continue

            # Titles from BOTH pages: the listing shows how this seller names
            # the model alongside competitors, the detail page gives its full
            # title. More independent titles means better corroboration.
            scraped_data.append({
                "url": detail.url,
                "source_type": source["source_type"],
                "content": detail.content,
                "candidate_titles": list(dict.fromkeys(
                    result.candidate_titles + detail.candidate_titles
                )),
            })

            matched_template = template_of_url(domain, source["url"], brand_name, model_number)
            if matched_template:
                await remember_working_template(domain, matched_template)
            break  # this domain answered; move to the next one

        # Feeds the diminishing-returns stop above. Counted per DOMAIN, not per
        # URL pattern: one domain legitimately costs several attempts while its
        # platform is identified, and counting those as separate misses would
        # abandon the list far too early.
        if len(scraped_data) > sources_before_domain:
            consecutive_empty_domains = 0
        else:
            consecutive_empty_domains += 1

    if not scraped_data:
