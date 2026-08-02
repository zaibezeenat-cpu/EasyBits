from pydantic import BaseModel, field_validator

class FAQPair(BaseModel):
    question: str
    answer: str

class WriterOutput(BaseModel):
    hero_heading: str
    hero_paragraph: str
    feature_headings: list[str]         # len==2 for Template B, len==3 for Template A
    feature_texts: list[str]            # same length as feature_headings
    features_bullets: list[str]         # 4-6 bullets
    faqs: list[FAQPair]                 # exactly 5; faqs[4] is ALWAYS the fixed warranty Q&A
    short_desc_feature_1: str
    short_desc_feature_2: str
    short_desc_feature_3: str

    # --- V8.0 Production Lock SEO fields ---
    # rank_math_focus_keyword is NO LONGER written by the LLM — it is locked
    # deterministically to the exact Product Name by the pipeline (nodes.py).
    # rank_math_title is NO LONGER written by the LLM — it is built
    # deterministically by app/builders/seo_title_builder.py ("Boss Title Rule").
    rank_math_description: str          # 151-155 chars; begins with focus keyword;
                                         # mentions warranty; ends with fixed CTA (validated in seo_validator.py)

    lsi_keywords: list[str]             # exactly 3 — must appear as PLAIN TEXT (no bold/header
                                         # wrapper) somewhere in the body copy (hero/feature text)
    alt_text_1: str                     # Template A image 1 alt text — focus keyword or an LSI keyword
    alt_text_2: str                     # Template A image 2 alt text — focus keyword or an LSI keyword
    alt_text_3: str                     # Template A image 3 alt text — focus keyword or an LSI keyword

    @field_validator("faqs")
    @classmethod
    def exactly_five_faqs(cls, v: list[FAQPair]) -> list[FAQPair]:
        if len(v) != 5:
            raise ValueError(f"WriterOutput.faqs must have exactly 5 entries, got {len(v)}")
        if v[4].question != "What is the official warranty?":
            raise ValueError("faqs[4].question must be the fixed warranty question, phase1.md §6.4")
        return v

    @field_validator("lsi_keywords")
    @classmethod
    def lsi_keyword_count_in_range(cls, v: list[str]) -> list[str]:
        # Exactly 2-3 LSI keywords. The exported rank_math_focus_keyword field is
        # "Primary + Secondary + these LSIs", so this lands at 4-5 keywords total.
        # Rank Math scores exactly the first 5 keywords, which is the perfect
        # sweet spot. Going higher pushes the density over 2.5% mathematically.
        if not (2 <= len(v) <= 3):
            raise ValueError(f"WriterOutput.lsi_keywords must have 2 to 3 entries, got {len(v)}")
        if any(not k.strip() for k in v):
            raise ValueError("WriterOutput.lsi_keywords entries must not be empty")
        if len(set(k.strip().lower() for k in v)) != len(v):
            raise ValueError("WriterOutput.lsi_keywords must be distinct (no duplicates)")
        return v
