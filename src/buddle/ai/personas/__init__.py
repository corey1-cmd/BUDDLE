"""Persona backend implementations + factory.

Public entry point: PersonaService. Construct with (db, redis) and call
.interpret() / .respond_in_dialogue() — backend dispatch and fallback
are handled internally.
"""

from buddle.ai.personas.factory import PersonaService
from buddle.ai.personas.local_hf import LocalHfPersona
from buddle.ai.personas.ondevice_webllm import OndeviceWebllmPersona
from buddle.ai.personas.vllm_endpoint import PersonaBackendError, VllmEndpointPersona

__all__ = [
    "LocalHfPersona",
    "OndeviceWebllmPersona",
    "PersonaBackendError",
    "PersonaService",
    "VllmEndpointPersona",
]
