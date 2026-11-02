"""Offline documentation and Python AST audit."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

from .phrases import SOUND, NOSOUND

GENERIC = {
    'detect_sound_event', 'detect_sound_events', 'detect_audio_event',
    'detect_audio_events', 'classify_sound_event', 'classify_sound_events',
    'recognize_sound_event', 'recognise_sound_event', 'tag_sound_event',
}


def normalize(text):
    return ' '.join(text.lower().replace("n't", ' not').replace('-', ' ').split())


def phrases_in(text):
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if match:
            fence = match[1]
            lines.append('')
        else:
            lines.append(line)
    found = set()
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        value = normalize(paragraph)
        for family, phrases in [('NOSOUND', NOSOUND), ('SOUND', SOUND)]:
            for phrase in sorted(phrases, key=lambda p: (-len(p), p)):
                pattern = r'\b' + re.escape(phrase) + r'\b'
                if re.search(pattern, value):
                    found.add(family)
                    value = re.sub(pattern, ' ', value)
    return found


def evidence(source):
    """Recognize supported call fingerprints within one parsed module."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    nodes = list(ast.walk(tree))
    aliases = {}
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = item.name
        elif isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name.split('.')[-1]
    shadows = {n.name for n in nodes
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

    def name(func):
        if isinstance(func, ast.Name):
            return aliases.get(func.id, func.id)
        return func.attr if isinstance(func, ast.Attribute) else ''

    def shadowed(func):
        return name(func) in shadows or (isinstance(func, ast.Name) and func.id in shadows)

    def literal(node):
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ''

    bindings = {}
    for node in nodes:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        kind = name(call.func)
        if kind == 'load':
            kind = 'hub_yamnet' if call.args and 'yamnet' in literal(call.args[0]).lower() else ''
        elif kind not in ('AudioTagging', 'YAMNet') or shadowed(call.func):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                bindings.setdefault(target.id, set()).add(kind)
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = name(func)
        if called == 'pipeline' and node.args and literal(node.args[0]) == 'audio-classification':
            model = node.args[1] if len(node.args) > 1 else next(
                (kw.value for kw in node.keywords if kw.arg == 'model'), None)
            if any(token in literal(model).lower() for token in ('yamnet', 'ast', 'panns', 'audioset')):
                return True
        if isinstance(func, ast.Name) and 'hub_yamnet' in bindings.get(func.id, set()):
            return True
        if shadowed(func):
            continue
        if called in GENERIC and (isinstance(func, ast.Attribute) or
                                  isinstance(func, ast.Name) and func.id in aliases):
            return True
        if isinstance(func, ast.Name) and 'YAMNet' in bindings.get(func.id, set()):
            return True
        if (isinstance(func, ast.Attribute) and func.attr == 'inference'
                and isinstance(func.value, ast.Name)
                and 'AudioTagging' in bindings.get(func.value.id, set())):
            return True
    return False


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir():
        raise OSError('root must be a readable directory')
    claims = set()
    production = []
    tests = []
    def walk_error(error):
        raise error
    for directory, dirs, files in os.walk(root, onerror=walk_error):
        relative = Path(directory).relative_to(root)
        def excluded(path):
            rel = path.relative_to(root).as_posix()
            return path.is_symlink() or any(rel == p.rstrip('/') or rel.startswith(p.rstrip('/') + '/') for p in ignore)
        dirs[:] = sorted(d for d in dirs if not excluded(Path(directory) / d))
        for filename in sorted(files):
            path = Path(directory) / filename
            if excluded(path):
                continue
            parts = path.relative_to(root).parts
            if (parts == ('README.md',) or ('docs' in parts[:-1] and path.suffix == '.md')):
                claims.update(phrases_in(path.read_text(encoding='utf-8')))
            if path.suffix != '.py' or any(p in parts[:-1] for p in ('fixtures', 'docs', 'examples')):
                continue
            is_test = 'tests' in parts[:-1] or filename.startswith('test_') or filename.endswith('_test.py')
            if evidence(path.read_text(encoding='utf-8')):
                (tests if is_test else production).append(path.relative_to(root).as_posix())
    findings = []
    if 'SOUND' in claims and not production:
        severity = 'MEDIUM' if tests else 'HIGH'
        findings.append({'id': 'documented-sound-event-detection-claim-false', 'severity': severity, 'message': 'Documentation claim has evidence only in tests.' if tests else 'Documentation claim has no production evidence.'})
    if 'NOSOUND' in claims and production:
        findings.append({'id': 'documented-no-sound-event-detection-claim-false', 'severity': 'HIGH', 'message': 'Documentation denial conflicts with production evidence.'})
    return {'verdict': 'FAIL' if findings else 'PASS', 'findings': findings, 'production_evidence': production, 'test_evidence': tests}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, '%s: error: %s\n' % (self.prog, message))


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('root')
    parser.add_argument('--version', action='version', version='0.1.0')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['LOW', 'MEDIUM', 'HIGH'], default='HIGH')
    args = parser.parse_args(argv)
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result['verdict'])
        for finding in result['findings']:
            print('{id} {severity}: {message}'.format(**finding))
        if args.verbose:
            print('Production evidence: ' + ', '.join(result['production_evidence']))
            print('Test evidence: ' + ', '.join(result['test_evidence']))
    levels = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    return 2 if any(levels[f['severity']] >= levels[args.fail_on] for f in result['findings']) else 0
