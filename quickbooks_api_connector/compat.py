"""Compatibility layer for optional SLATE v19 integration.

When slate_connector_v19 is installed alongside this module, these helpers
delegate to the SLATE integration registry, event bus, and cross-entity map.
When SLATE is absent, they gracefully no-op so the module works standalone.
"""
import logging

_logger = logging.getLogger(__name__)


def get_integration_registry(env):
    """Return the SLATE integration registry model, or None if not installed."""
    if 'slate.integration.registry' in env:
        return env['slate.integration.registry']
    return None


def fire_integration_event(env, *args, **kwargs):
    """Fire a SLATE integration event if the event bus exists, otherwise no-op."""
    if 'slate.integration.event' in env:
        try:
            env['slate.integration.event'].fire(*args, **kwargs)
        except Exception:
            _logger.debug('Integration event fire failed (non-critical)', exc_info=True)


def update_cross_entity_map(env, **kwargs):
    """Update a cross-entity mapping if the model exists, otherwise no-op."""
    if 'slate.cross.entity.map' in env:
        try:
            env['slate.cross.entity.map'].update_mapping(**kwargs)
        except Exception:
            _logger.debug('Cross-entity map update failed (non-critical)', exc_info=True)
