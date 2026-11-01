"""The two prompts, word for word as they were. What changed is how they are sent: the old code
wrapped each one in a JSON object and then deleted every backslash, so each paragraph break
(``\\n\\n``) reached the model as the letters ``nn``. They are now sent as plain text."""

SYSTEM = "You are a helpful assistant."


def short_description_prompt(product_title, short_description, categories_string):
    return (
        "As a product analyst, your task is to update and create a compelling product listings for our B2B marketplace. "
        f"Start with the base description: '{short_description}'. If the product has a chemical formula or CAS number, integrate "
        "pertinent details from your data up to September 2021. For other products in the marketplace, use your general product knowledge "
        "to enhance and expand the listing. Filter out irrelevant supplier data and unnecessary product specifics. "
        f"Craft a compelling 150-word short description in HTML for product '{product_title}'. Employ bullet points when presenting crucial details, "
        "apply bold formatting to emphasize keywords in each bullet point, and omit any nonessential supplier specifics or irrelevant product data. "
        "IMPORTANT: If specific data for an attribute like CAS number or chemical formula isn't known, SKIP that attribute entirely. Do not use placeholders like 'Not available' or 'still being determined'. "
        f"Also, select up to three categories from the following list that the product could belong to: {categories_string}..."
        'Please return ONLY a JSON object with the following keys: "short_description", "categories".'
        'The "categories" should be a list of category IDs. No additional text or formatting is needed.'
    )


def long_description_prompt(product_title, long_description):
    return (
        "As a product analyst, your task is to update and create a compelling product listings for our B2B marketplace. "
        "For products that have CAS or a chemical formula, you can look for those attributes from the following list if available: "
        "Compound Name, Synonyms, IUPAC Name, CAS Number, Molecular Formula, Molecular Weight, Canonical SMILES, InChI strings, "
        "Boiling Point, Melting Point, Flash Point, Density, Solubility, Vapor Pressure, Refractive Index, pH, LogP, Polar Surface Area, "
        "Rotatable Bond Count, Hazard and Precautionary Statements, GHS Classification, LD50, Routes of Exposure, Carcinogenicity, "
        "Teratogenicity, Bioassay Results, Target Proteins, Mechanism of Action, Pharmacological Class, ADME data, NMR, MS, IR, UV-Vis, "
        "Environmental Fate, Biodegradability, Ecotoxicity, Therapeutic Uses, Dosage, Contraindications, Side Effects, Drug Interactions.\n\n"
        "For other products in the marketplace, use your general product knowledge data up to September 2021 to help enhance and expand the listing. "
        f"Start by utilizing the initial description provided: '{long_description}'. After gathering the details, craft a compelling 1000-word "
        f"detail product description in HTML highlighting the product's key features for '{product_title}'. Use bullet points for vital information "
        "and exclude any unrelated supplier specifics or non-pertinent product data.\n\n"
        "IMPORTANT: If specific data for an attribute isn't known, SKIP that attribute entirely. Do not use placeholders like 'Not available'.\n\n"
        "Also, generate an SEO-friendly title for this product, a meta description that is under 155 characters, a focus keyword based on the meta description, and a list of relevant product tags.\n\n"
        'Please return ONLY a JSON object with the following keys: "long_description", "seo_title", "meta_description", "focus_keyword", "tags". No additional text or formatting is needed.'
    )
