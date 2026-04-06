"""Demo application for cjm-fasthtml-workflow-transcript-decomp library.

This demo showcases the structure decomposition workflow:

1. StructureDecompWorkflow:
   - Receives PluginManager from host application (dependency injection)
   - SQLite-backed state persistence across restarts
   - 3-step wizard: Selection -> Segment & Align -> Review

2. PluginManager:
   - Discovers plugins from JSON manifests in ~/.cjm/manifests/
   - Process-isolated plugin execution via RemotePluginProxy
   - Resource-aware scheduling (optional SafetyScheduler/QueueScheduler)

3. The "Four Pillars" (required plugins):
   - Text: cjm-text-plugin-nltk (sentence splitting)
   - Media: cjm-media-plugin-silero-vad (audio alignment)
   - Graph: cjm-graph-plugin-sqlite (storage)
   - Source: Any transcription plugin (e.g., cjm-transcription-plugin-whisper)

4. StepFlow Integration:
   - Phase 1: Source Selection & Ordering
   - Phase 2: Segment & Align (Dual-Column UI)
   - Phase 3: Review & Commit

Run with plugins installed via `cjm-ctl install-all --plugins plugins_test.yaml`.
"""

from pathlib import Path
import atexit


def main():
    """Main entry point - initializes workflow and starts the server."""
    from fasthtml.common import fast_app, Div, H1, P, Span, A, Code, APIRouter
    from cjm_fasthtml_daisyui.core.resources import get_daisyui_headers
    from cjm_fasthtml_daisyui.core.testing import create_theme_persistence_script
    from cjm_fasthtml_app_core.components.navbar import create_navbar
    from cjm_fasthtml_app_core.core.routing import register_routes
    from cjm_fasthtml_app_core.core.htmx import handle_htmx_request
    from cjm_fasthtml_app_core.core.layout import wrap_with_layout

    # Import styling utilities
    from cjm_fasthtml_tailwind.utilities.spacing import p, m
    from cjm_fasthtml_tailwind.utilities.sizing import container, max_w, w, h
    from cjm_fasthtml_tailwind.utilities.typography import font_size, font_weight, text_align
    from cjm_fasthtml_tailwind.core.base import combine_classes
    from cjm_fasthtml_daisyui.components.actions.button import btn, btn_colors, btn_sizes
    from cjm_fasthtml_daisyui.components.data_display.badge import badge, badge_colors
    from cjm_fasthtml_daisyui.components.feedback.alert import alert, alert_colors

    print("\n" + "="*70)
    print("Initializing cjm-fasthtml-workflow-transcript-decomp Demo")
    print("="*70)

    # Import plugin system components
    from cjm_plugin_system.core.manager import PluginManager
    from cjm_plugin_system.core.scheduling import QueueScheduler

    # Import workflow components
    from cjm_fasthtml_workflow_transcript_decomp.workflow.workflow import StructureDecompWorkflow
    from cjm_fasthtml_workflow_transcript_decomp.core.config import StructureDecompWorkflowConfig

    # Import management components
    from cjm_transcript_workflow_management.services.management import ManagementService
    from cjm_transcript_workflow_management.routes.init import init_management_routers

    print("  Library components imported successfully")

    # SSE headers (for job monitor — harmless if FA unavailable)
    from cjm_fasthtml_job_monitor.components.modal import get_sse_headers

    # Create the FastHTML app
    APP_ID = "txdecomp"

    app, rt = fast_app(
        pico=False,
        hdrs=[
            *get_daisyui_headers(),
            create_theme_persistence_script(),
            *get_sse_headers(),
        ],
        title="Structure Decomposition Workflow Demo",
        htmlkw={'data-theme': 'light'},
        session_cookie=f'session_{APP_ID}_',
        secret_key=f'{APP_ID}-demo-secret',
    )

    router = APIRouter(prefix="")

    print("  FastHTML app created successfully")

    # Create the PluginManager (host application responsibility)
    print("\n[1/3] Creating PluginManager...")
    plugin_manager = PluginManager(scheduler=QueueScheduler())

    # Discover plugins from JSON manifests
    plugin_manager.discover_manifests()

    # Load the "Four Pillar" plugins
    pillar_plugins = {
        "cjm-text-plugin-nltk": {"language": "english"},
        "cjm-media-plugin-silero-vad": {"threshold": 0.5},
        "cjm-graph-plugin-sqlite": None,
    }

    print("\n  Loading pillar plugins:")
    for plugin_name, config in pillar_plugins.items():
        meta = plugin_manager.get_discovered_meta(plugin_name)
        if meta:
            try:
                success = plugin_manager.load_plugin(meta, config)
                status = "loaded" if success else "failed"
                print(f"    - {plugin_name}: {status}")
            except Exception as e:
                print(f"    - {plugin_name}: error - {e}")
        else:
            print(f"    - {plugin_name}: not found")

    # Load any discovered transcription plugins
    transcription_plugins = plugin_manager.get_discovered_by_category("transcription")
    print(f"\n  Discovered {len(transcription_plugins)} transcription plugins")

    for meta in transcription_plugins:
        try:
            success = plugin_manager.load_plugin(meta)
            status = "loaded" if success else "failed"
            print(f"    - {meta.name}: {status}")
        except Exception as e:
            print(f"    - {meta.name}: error - {e}")

    # Optionally load system monitor for resource-aware scheduling
    sysmon_name = None
    monitors = plugin_manager.get_discovered_by_category("system_monitor")
    if monitors:
        try:
            plugin_manager.load_plugin(monitors[0])
            plugin_manager.register_system_monitor(monitors[0].name)
            sysmon_name = monitors[0].name
            print(f"\n  System monitor registered: {monitors[0].name}")
        except Exception as e:
            print(f"\n  System monitor failed to load: {e}")

    # Register cleanup on exit
    def cleanup_plugins():
        print("\n[Cleanup] Unloading all plugins...")
        plugin_manager.unload_all()
        print("[Cleanup] Done")

    atexit.register(cleanup_plugins)

    # Create the structure decomposition workflow
    print("\n[2/3] Creating and setting up StructureDecompWorkflow...")

    config = StructureDecompWorkflowConfig(
        route_prefix="/workflow",
        no_plugins_redirect="/",
        sysmon_plugin_name=sysmon_name,
        show_progress=True
    )

    structure_workflow = StructureDecompWorkflow.create_and_setup(
        app,
        plugin_manager=plugin_manager,
        config=config,
    )

    print("  Workflow created and setup complete")

    # Store workflow in app.state for access from routes
    app.state.structure_workflow = structure_workflow
    app.state.plugin_manager = plugin_manager

    # Create management service (shares the same plugin_manager / graph plugin)
    mgmt_service = ManagementService(plugin_manager, "cjm-graph-plugin-sqlite")
    mgmt_result = init_management_routers(
        service=mgmt_service,
        prefix="/manage",
    )
    print(f"\n  Management service available: {mgmt_service.is_available()}")

    # Check plugin and source status
    sources = structure_workflow.source_service.get_available_sources()
    print(f"\n  Available sources: {len(sources)}")
    for src in sources:
        print(f"    - {src['name']}")

    # Define routes
    @router
    def index(request):
        """Homepage with workflow overview and entry point."""

        def home_content():
            # Get current status
            all_sources = structure_workflow.source_service.get_available_sources()
            loaded_plugins = plugin_manager.list_plugins()

            return Div(
                H1("Structure Decomposition Workflow Demo",
                   cls=combine_classes(font_size._4xl, font_weight.bold, m.b(4))),

                P("A human-in-the-loop workflow for decomposing raw transcripts:",
                  cls=combine_classes(font_size.lg, m.b(6))),

                # Feature list
                Div(
                    Div(
                        Span("", cls=combine_classes(font_size._2xl, m.r(3))),
                        Span("Phase 1: Source Selection & Ordering"),
                        cls=combine_classes(m.b(3))
                    ),
                    Div(
                        Span("", cls=combine_classes(font_size._2xl, m.r(3))),
                        Span("Phase 2: Segment & Align (Dual-Column UI)"),
                        cls=combine_classes(m.b(3))
                    ),
                    Div(
                        Span("", cls=combine_classes(font_size._2xl, m.r(3))),
                        Span("Phase 3: Review & Commit to Context Graph"),
                        cls=combine_classes(m.b(8))
                    ),
                    cls=combine_classes(text_align.left, m.b(8))
                ),

                # Status badges
                Div(
                    Span(
                        Span(f"{len(loaded_plugins)}", cls=str(font_weight.bold)),
                        " Plugins",
                        cls=combine_classes(
                            badge,
                            badge_colors.info if loaded_plugins else badge_colors.warning,
                            m.r(2)
                        )
                    ),
                    Span(
                        Span(f"{len(all_sources)}", cls=str(font_weight.bold)),
                        " Sources",
                        cls=combine_classes(
                            badge,
                            badge_colors.success if all_sources else badge_colors.warning
                        )
                    ),
                    cls=combine_classes(m.b(8))
                ),

                # Action buttons
                Div(
                    A(
                        "Start Structure Decomposition",
                        href="/workflow",
                        cls=combine_classes(btn, btn_colors.primary, btn_sizes.lg, m.r(2))
                    ),
                ),

                # Info message if no sources
                Div(
                    Div(
                        Span("Info: ", cls=str(font_weight.bold)),
                        "No transcription sources available. Install a transcription plugin ",
                        "(e.g., ", Code("cjm-transcription-plugin-whisper"), ") ",
                        "and create some transcriptions to enable this workflow.",
                        cls=combine_classes(alert, alert_colors.info, m.t(8))
                    )
                ) if not all_sources else None,

                cls=combine_classes(
                    container,
                    max_w._4xl,
                    m.x.auto,
                    p(8),
                    text_align.center
                )
            )

        return handle_htmx_request(
            request,
            home_content,
            wrap_fn=lambda content: wrap_with_layout(content, navbar=navbar)
        )

    @router
    def workflow(request, sess):
        """Render the structure decomposition workflow."""

        def workflow_content():
            return Div(
                structure_workflow.render_entry_point(request, sess),
                cls=combine_classes(w.full, h.full, p(4))
            )

        return handle_htmx_request(
            request,
            workflow_content,
            wrap_fn=lambda content: wrap_with_layout(content, navbar=navbar)
        )

    @router
    async def manage(request):
        """Graph management page — list, inspect, delete, import/export documents."""
        await mgmt_result.refresh_items()
        return handle_htmx_request(
            request,
            mgmt_result.render_page,
            wrap_fn=lambda content: wrap_with_layout(content, navbar=navbar)
        )

    # Create navbar (after routes are defined so we can reference them)
    navbar = create_navbar(
        title="Structure Decomp Demo",
        nav_items=[
            ("Home", index),
            ("Workflow", workflow),
            ("Manage", manage),
        ],
        home_route=index,
        theme_selector=True
    )

    # Register all routes
    print("\n[3/3] Registering routes...")
    register_routes(
        app,
        router,
        *structure_workflow.get_routers(),
        *mgmt_result.routers,
    )

    # JobQueue lifecycle hooks
    @app.on_event("startup")
    async def on_startup():
        await structure_workflow.job_queue.start()
        print("Job queue started")

    @app.on_event("shutdown")
    async def on_shutdown():
        await structure_workflow.job_queue.stop()
        print("Job queue stopped")

    # Debug: Print registered routes
    print("\n" + "="*70)
    print("Registered Routes:")
    print("="*70)
    for route in app.routes:
        if hasattr(route, 'path'):
            print(f"  {route.path}")

    print("\n" + "="*70)
    print("Demo App Ready!")
    print("="*70)
    print("\n Library Components:")
    print("  - PluginManager - Plugin discovery and lifecycle")
    print("  - StructureDecompWorkflow - Main workflow orchestrator")
    print("  - SQLiteWorkflowStateStore - Persistent state storage")
    print("  - SourceService - DuckDB federated queries")
    print("  - SegmentationService - NLTK sentence splitting")
    print("  - AlignmentService - Silero VAD analysis")
    print("  - GraphService - Context graph commit")
    print("  - StepFlow integration - 3-step wizard")
    print("="*70 + "\n")

    return app


if __name__ == "__main__":
    import uvicorn
    import webbrowser
    import threading

    # Call main to initialize everything and get the app
    app = main()

    def open_browser(url):
        print(f"Opening browser at {url}")
        webbrowser.open(url)

    port = 5031
    host = "0.0.0.0"
    display_host = 'localhost' if host in ['0.0.0.0', '127.0.0.1'] else host

    print(f"Server: http://{display_host}:{port}")
    print("\nAvailable routes:")
    print(f"  http://{display_host}:{port}/          - Homepage with status")
    print(f"  http://{display_host}:{port}/workflow  - Structure decomposition workflow")
    print(f"  http://{display_host}:{port}/manage   - Graph management (list, inspect, delete, import/export)")
    print("\n" + "="*70 + "\n")

    # Open browser after a short delay
    timer = threading.Timer(1.5, lambda: open_browser(f"http://localhost:{port}"))
    timer.daemon = True
    timer.start()

    # Start server
    uvicorn.run(app, host=host, port=port)
