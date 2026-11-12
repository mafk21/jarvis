"""Discoverable, provider-neutral persistent study action for voice and text sessions."""
from __future__ import annotations

import json


def topic_learning(parameters: dict, player=None, **_) -> str:
    from core import topic_learning as learning
    p = parameters or {}
    action = str(p.get('action', 'learn')).lower().strip()
    topic = str(p.get('topic', '')).strip()
    try:
        if action in ('learn', 'continue'):
            result = learning.study(topic, progress=(getattr(player, 'write_log', None) or (lambda _: None)))
            if player and hasattr(player, 'show_content'):
                player.show_content('SAVED STUDY', json.dumps(result, ensure_ascii=False, indent=2))
            return json.dumps(result, ensure_ascii=False) + (
                '\nA bounded study unit was saved and passed a retrieval-assisted model review; '
                'this is not proof of mastery or a model-weight update.' if result['status'] == 'studied' else
                '\nDo not claim this topic was learned successfully. Report the saved status and any error/gaps.')
        if action == 'list':
            return json.dumps(learning.catalog(), ensure_ascii=False, indent=2)
        if action in ('read', 'status'):
            return learning.read_topic(topic, str(p.get('run_id', '')))
        if action == 'search':
            return learning.search(str(p.get('query') or topic))
        return 'Unknown study action. Use learn, continue, list, status, read or search.'
    except Exception as exc:
        return f'Study failed; no success claimed: {exc}'


TOOL = {
    'name': 'topic_learning',
    'description': (
        'Actually study and retain a subject when asked to learn/study/master it (e.g. nuclear physics). '
        'Researches sources, defines measurable scope coverage, saves multi-depth evidence-linked concepts and typed '
        'connections, compares support, tracks freshness, tests retrieval, reviews answers and records gaps '
        'in memory/learning/. External-memory learning, NOT weight training. Actions: learn/continue '
        '(one bounded unit), list, status/read (topic, optional run_id), search (query). '
        'Use search/read to apply learned material in future answers; never claim success unless the stored result says studied.'
    ),
    'parameters': {
        'type': 'OBJECT',
        'properties': {
            'action': {'type': 'STRING', 'enum': ['learn', 'continue', 'list', 'status', 'read', 'search']},
            'topic': {'type': 'STRING', 'description': 'Subject to study or exact topic title from list/search.'},
            'query': {'type': 'STRING', 'description': 'Words to retrieve from saved study material.'},
            'run_id': {'type': 'STRING', 'description': 'Optional saved unit ID from status/list for historical reading.'},
        },
        'required': ['action'],
    },
    'handler': topic_learning,
    'behavior': 'NON_BLOCKING',
    'scheduling': 'WHEN_IDLE',
}
