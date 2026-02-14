"""Manual test script for GraphService — verifies commit writes to SQLite database.

Run from project root:
    python tests_manual/test_graph_service.py
"""

import asyncio
from pathlib import Path

from cjm_plugin_system.core.manager import PluginManager

from cjm_fasthtml_workflow_transcript_decomp.review.services.graph import GraphService
from cjm_fasthtml_workflow_transcript_decomp.review.models import WorkingDocument
from cjm_fasthtml_workflow_transcript_decomp.decomposition.models import TextSegment


async def main():
    # --- Setup ---
    project_root = Path(__file__).parent.parent
    manifests_dir = project_root / ".cjm" / "manifests"

    manager = PluginManager(search_paths=[manifests_dir])
    manager.discover_manifests()
    print(f"Discovered {len(manager.discovered)} plugins from {manifests_dir}")

    graph_meta = manager.get_discovered_meta("cjm-graph-plugin-sqlite")
    if not graph_meta:
        print("ERROR: cjm-graph-plugin-sqlite not found — install via plugins.yaml")
        return

    print(f"Found plugin: {graph_meta.name} v{graph_meta.version}")

    # Load the plugin
    manager.load_plugin(graph_meta)
    graph_service = GraphService(manager)
    print(f"Plugin available: {graph_service.is_available()}")

    # --- Commit a WorkingDocument ---
    working_doc = WorkingDocument(
        title="The Art of War - Chapter 1",
        media_type="audio",
        media_path="/path/to/audio.mp3",
    )

    working_doc.segments = [
        TextSegment(
            index=0,
            text="Laying Plans",
            source_id="job_123",
            source_provider_id="test-plugin",
            start_char=0,
            end_char=12,
            start_time=0.0,
            end_time=1.5,
        ),
        TextSegment(
            index=1,
            text="Sun Tzu said: The art of war is of vital importance to the state.",
            source_id="job_123",
            source_provider_id="test-plugin",
            start_char=13,
            end_char=79,
            start_time=1.5,
            end_time=5.0,
        ),
        TextSegment(
            index=2,
            text="It is a matter of life and death, a road either to safety or to ruin.",
            source_id="job_123",
            source_provider_id="test-plugin",
            start_char=80,
            end_char=150,
            start_time=5.0,
            end_time=9.0,
        ),
    ]

    print(f"\nCommitting document with {len(working_doc.segments)} segments...")
    result = await graph_service.commit_document_async(working_doc)

    print(f"\nCommit result:")
    print(f"  Document ID: {result['document_id']}")
    print(f"  Segment IDs: {result['segment_ids']}")
    print(f"  Edge count:  {result['edge_count']}")

    # --- Verify graph structure ---
    schema = await manager.execute_plugin_async(
        "cjm-graph-plugin-sqlite",
        action="get_schema",
    )
    print(f"\nGraph schema:")
    print(f"  Node labels:    {schema.get('node_labels', [])}")
    print(f"  Relation types: {schema.get('relation_types', [])}")

    # --- Query back the nodes we just wrote ---
    doc_node = await manager.execute_plugin_async(
        "cjm-graph-plugin-sqlite",
        action="get_node",
        node_id=result["document_id"],
    )
    print(f"\nRetrieved Document node:")
    print(f"  ID:    {doc_node.get('id')}")
    print(f"  Label: {doc_node.get('label')}")
    print(f"  Title: {doc_node.get('properties', {}).get('title')}")

    for seg_id in result["segment_ids"]:
        seg_node = await manager.execute_plugin_async(
            "cjm-graph-plugin-sqlite",
            action="get_node",
            node_id=seg_id,
        )
        props = seg_node.get("properties", {})
        print(f"  Segment [{props.get('index')}]: '{props.get('text', '')[:40]}...'")

    # --- Cleanup ---
    manager.unload_all()
    print("\nPlugins unloaded. Done.")


if __name__ == "__main__":
    asyncio.run(main())
