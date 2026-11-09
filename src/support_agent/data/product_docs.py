"""Extract catalog entries from model codes on PDF cover pages, never filenames."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from pypdf import PdfReader

from support_agent.config import DocsSettings
from support_agent.data.doc_models import Product, digest, normalise


def product_category(model: str, settings: DocsSettings) -> str:
    for prefix, category in settings.product_categories.items():
        if model.startswith(prefix):
            return category
    return settings.product_categories["monitor"]


def extract_products(raw_dir: Path, settings: DocsSettings) -> list[Product]:
    products: list[Product] = []
    for archive in sorted((raw_dir / "philips_manuals").glob("*.zip")):
        with zipfile.ZipFile(archive) as handle:
            for name in sorted(handle.namelist()):
                if not name.lower().endswith(".pdf"):
                    continue
                reader = PdfReader(io.BytesIO(handle.read(name)))
                pages = [page.extract_text() or "" for page in reader.pages]
                models = sorted(set(re.findall(settings.model_pattern, normalise(pages[0]))))
                if not models:
                    raise ValueError(f"No cover model found in {name}")
                text = normalise("\n".join(pages))
                source_id = f"philips_manuals:{archive.name}:{name}"
                # Keep only explicit key:value specs, with their original keys and values.
                attributes = dict(re.findall(r"^([^:\n]+):\s*([^\n]+)$", "\n".join(pages), re.M))
                attributes = {normalise(k): normalise(v) for k, v in attributes.items()}
                for model in models:
                    products.append(
                        Product(
                            product_id="philips-" + digest(model),
                            model=model,
                            name=f"Philips {model}",
                            attributes=attributes if len(models) == 1 else {},
                            description=text,
                            source_id=source_id,
                        )
                    )
    if not products:
        raise ValueError("No product PDFs found; run make data-download")
    if len({p.model for p in products}) != len(products):
        raise ValueError("Duplicate catalog models")
    return sorted(products, key=lambda p: p.model)


def product_section_id(model: str) -> str:
    # Exact model spelling is kept; slashes are valid in HTML comment identifiers.
    return f"product.{model}"
