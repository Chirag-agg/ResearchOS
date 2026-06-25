import pytest
from app.pipeline.core import PipelineContext
from app.pipeline.ir import SourceDocument, DocumentNode, HeadingNode, ParagraphNode
from app.pipeline.adapters.html_adapter import HTMLAdapter

@pytest.fixture
def context():
    return PipelineContext(session_id="test", document_id="test")

@pytest.mark.asyncio
async def test_html_adapter_builds_ir(context):
    html = """
    <html>
        <body>
            <h1>Test Document</h1>
            <p>This is a paragraph.</p>
            <table>
                <tr><td>Cell</td></tr>
            </table>
        </body>
    </html>
    """
    
    source = SourceDocument(id="test-id", source_type="HTML", raw_content=html.encode("utf-8"))
    adapter = HTMLAdapter()
    
    result = await adapter.process(source, context)
    assert result.status == "SUCCESS"
    
    root: DocumentNode = result.output
    assert root.node_type == "DOCUMENT"
    assert len(root.children) == 3
    
    heading = root.children[0]
    assert heading.node_type == "HEADING"
    assert heading.text == "Test Document"
    assert heading.provenance.source_tag == "h1"
    
    paragraph = root.children[1]
    assert paragraph.node_type == "PARAGRAPH"
    assert paragraph.text == "This is a paragraph."
    
    table = root.children[2]
    assert table.node_type == "TABLE"
