scraped_data: list[dict[str, str]] = []
attempted = 0
blocked = False
resolved_domains = set()
for pass_num, allow_tier2 in [(1, False), (2, True)]:
    if pass_num == 2 and _corroboration_satisfied(scraped_data):
        break
    if pass_num == 2:
        pending_domains = len([d for d in by_domain.keys() if d not in resolved_domains])
        if pending_domains == 0:
            break
        logger.info(f"Pass 1 exhausted for {model_number}. Beginning Pass 2 (Playwright allowed) for {pending_domains} domain(s).")
    consecutive_empty_domains = 0
    for domain, candidates in by_domain.items():
        if domain in resolved_domains:
            continue
        if _corroboration_satisfied(scraped_data):
            logger.info(
                f"Corroboration satisfied for {brand_name} {model_number} with "
                f"{len(scraped_data)} source(s) including an official one after "
                f"{attempted} attempt(s); further sources cannot change the result."
            )
            break
        if consecutive_empty_domains >= MAX_CONSECUTIVE_EMPTY_DOMAINS:
            logger.info(
                f"{consecutive_empty_domains} consecutive domains yielded nothing for "
                f"{brand_name} {model_number}; stopping with {len(scraped_data)} source(s) "
                f"rather than walking the remaining {len(by_domain) - attempted} domain(s)."
            )
            break
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
        domain_resolved = False
        for source in candidates:
            attempted += 1
            try:
                result = await smart_fetch(source["url"], model_number, allow_tier2=allow_tier2)
            except Exception as e:
                logger.warning(f"Scrape failed for {source['url']}: {e}")
                continue
            if not result.success or not result.content:
                continue
            if is_block_page(result.content):
                blocked = True
                logger.warning(
                    f"{source['url']} returned an anti-bot/block page (Cloudflare etc.); "
                    f"skipping." + (" (Tier 2 eligible)" if not allow_tier2 else "")
                )
                continue
            if not search_result_mentions_product(result.content, model_number):
                brand_token = re.split(r"[^a-zA-Z0-9]", brand_name)[0] if brand_name else brand_name
                if search_result_mentions_product(result.content, brand_token):
                    logger.info(
                        f"Domain {domain} confirmed: search works (mentions '{brand_name}') "
                        f"but '{model_number}' is not stocked there. "
                        f"Skipping {len(candidates) - candidates.index(source) - 1} "
                        f"remaining URL pattern(s) for this domain."
                    )
                    domain_resolved = True
                    break  
                logger.debug(
                    f"{source['url']} loaded but does not mention {model_number}; "
                    f"treating as no-match"
                )
                continue
            if source.get("is_direct") == "true":
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
                detail = await _follow_to_detail_page(
                    result,
                    model_number,
                    brand_name=brand_name,
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
                    domain_resolved = True
                    break
                continue
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
            
            domain_resolved = True
            break  
        if domain_resolved:
            resolved_domains.add(domain)
        if len(scraped_data) > sources_before_domain:
            consecutive_empty_domains = 0
        else:
            consecutive_empty_domains += 1
