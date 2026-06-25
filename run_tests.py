import asyncio
from app.pipeline.core import PipelineContext
from tests.pipeline.adapters.test_html_adapter import test_html_adapter_builds_ir, context
from app.pipeline.validation.structural import StructuralValidationStage
from app.pipeline.diagnostics.visualizer import VisualizerStage

async def run():
    print("Running adapter test...")
    ctx = PipelineContext(session_id="test", document_id="test")
    # Actually just call the adapter locally to get the root node
    from app.pipeline.adapters.html_adapter import HTMLAdapter
    from app.pipeline.ir import SourceDocument
    
    from app.pipeline.classifiers.section import SectionClassifierStage
    
    html = """
    <html>
        <body>
            <h1>Test Document</h1>
            <p>This is a paragraph before abstract.</p>
            <h2>Abstract</h2>
            <p>This is the abstract.</p>
            <h2>Methods</h2>
            <p>Method details.</p>
            <h3>Sub method</h3>
            <p>Sub details.</p>
            <h2>Results</h2>
            <table>
                <tr><td>Cell</td></tr>
            </table>
        </body>
    </html>
    """
    source = SourceDocument(id="test-id", source_type="HTML", raw_content=html.encode("utf-8"))
    adapter = HTMLAdapter()
    result = await adapter.process(source, ctx)
    root = result.output
    
    print("Running Section Classifier...")
    classifier = SectionClassifierStage()
    class_result = await classifier.process(root, ctx)
    root = class_result.output
    
    from app.pipeline.generators.artifact import ArtifactGeneratorStage
    print("Running Artifact Generator...")
    artifact_gen = ArtifactGeneratorStage()
    art_result = await artifact_gen.process(root, ctx)
    artifacts = art_result.output
    print(f"Generated {len(artifacts)} Rich Artifacts.")
    for a in artifacts:
        print(f"[{a.section_role}] {a.artifact_type}: Math={a.struct_contains_math}, Sentences={a.stat_sentence_count}, Entities={[e.mention_text for e in a.entity_mentions]}")
    
    print("Running validation...")
    validator = StructuralValidationStage()
    val_result = await validator.process(root, ctx)
    print(f"Validation Integrity Score: {val_result.metrics.get('structural_integrity')}")
    
    from app.pipeline.extractors.table import TableExtractorStage
    from app.pipeline.extractors.equation import EquationExtractorStage
    from app.pipeline.extractors.reference import ReferenceExtractorStage
    
    print("Running Specialized Extractors...")
    t_ex = TableExtractorStage()
    e_ex = EquationExtractorStage()
    r_ex = ReferenceExtractorStage()
    
    t_res = await t_ex.process(root, ctx)
    e_res = await e_ex.process(root, ctx)
    r_res = await r_ex.process(root, ctx)
    
    print(f"Extracted {len(t_res.artifacts)} Tables, {len(e_res.artifacts)} Equations, {len(r_res.artifacts)} References")
    
    print("Generating Visual Debugger HTML...")
    visualizer = VisualizerStage()
    vis_result = await visualizer.process(root, ctx)
    with open("tests/fixtures/html/document_ir_test.html", "w", encoding="utf-8") as f:
        f.write(vis_result.output)
    print("SUCCESS: Visual Debugger generated at tests/fixtures/html/document_ir_test.html")

if __name__ == "__main__":
    asyncio.run(run())
