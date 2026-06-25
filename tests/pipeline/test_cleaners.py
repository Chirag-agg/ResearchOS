import pytest
import os
from app.pipeline.core import PipelineContext
from app.pipeline.cleaners.html_normalizer import HTMLNormalizer
from app.pipeline.cleaners.unicode_normalizer import UnicodeNormalizer
from app.pipeline.cleaners.boilerplate_remover import BoilerplateRemover
from app.pipeline.cleaners.reading_order_resolver import ReadingOrderResolver
from app.pipeline.cleaners.whitespace_normalizer import WhitespaceNormalizer

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures", "html")

@pytest.fixture
def academic_html():
    with open(os.path.join(FIXTURES_DIR, "academic_nature.html"), "r", encoding="utf-8") as f:
        return f.read()

@pytest.fixture
def context():
    return PipelineContext(session_id="test", document_id="test", benchmark_mode=True)

@pytest.mark.asyncio
async def test_boilerplate_remover_preserves_signal(academic_html, context):
    remover = BoilerplateRemover()
    result = await remover.process(academic_html, context)
    
    html = result.output
    # Should remove ads and navigation
    assert "cookie-banner" not in html
    assert "top-nav" not in html
    assert "Buy our premium subscription" not in html
    assert "Recommended Reading" not in html
    
    # Should preserve equations, code, tables
    assert "<math" in html
    assert "<pre" in html
    assert "<table" in html

@pytest.mark.asyncio
async def test_unicode_normalizer(context):
    normalizer = UnicodeNormalizer()
    bad_unicode = "We achieved 94% – 95% accuracy. The length is 5 µm. The length is 5 μm."
    result = await normalizer.process(bad_unicode, context)
    
    # Hyphens unified to '-' and micro signs unified to 'μ'
    assert result.output == "We achieved 94% - 95% accuracy. The length is 5 μm. The length is 5 μm."

@pytest.mark.asyncio
async def test_reading_order_resolver(academic_html, context):
    # First remove boilerplate, then test reading order
    remover = BoilerplateRemover()
    clean_html = (await remover.process(academic_html, context)).output
    
    resolver = ReadingOrderResolver()
    result = await resolver.process(clean_html, context)
    
    blocks = result.output
    assert isinstance(blocks, list)
    assert len(blocks) > 0
    # The ad shouldn't be in the reading order since it was removed
    # Equations, paragraphs, headers should be distinct blocks
    assert any("<math" in b for b in blocks)
    assert any("<table" in b for b in blocks)
