"""Orchestration layer: composes providers into end-to-end services.

Modules here depend on providers and services but are depended on only by
the server layer. Layer order (lower depends on nothing above):

    core < security < observability < services < providers < orchestration < server
"""
