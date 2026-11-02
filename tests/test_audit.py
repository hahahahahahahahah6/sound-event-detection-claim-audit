import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sound_event_detection_claim_audit.audit import audit, evidence, phrases_in
from sound_event_detection_claim_audit import phrases

EXPECTED_SOUND = ('sound event detection', 'detects sound events', 'detect sound events', 'sound event recognition', 'recognizes sound events', 'recognises sound events', 'audio event detection', 'detects audio events', 'detect audio events', 'environmental sound detection', 'detects environmental sounds', 'acoustic event detection', 'detects acoustic events', 'detect acoustic events', 'sound event classification', 'classifies sound events', 'audio event recognition', 'recognizes audio events', 'sound event monitoring', 'monitors sound events', 'detects sirens', 'detects gunshots', 'detects glass breaking', 'detects baby cries', 'detects dog barks', 'detects alarms', 'alarm sound detection', 'siren detection', 'gunshot detection', 'glass break detection', 'baby cry detection', 'dog bark detection', 'environmental sound recognition', 'recognizes environmental sounds', 'sound event detector', 'supports sound event detection', 'sound event detection support', 'real time sound event detection', 'live sound event detection', 'detects everyday sounds', 'everyday sound detection', 'detects non speech sounds')
EXPECTED_NOSOUND = ('no sound event detection', 'does not detect sound events', 'without sound event detection', 'no audio event detection', 'does not detect audio events', 'without audio event detection', 'no environmental sound detection', 'sound event detection not supported', 'does not support sound event detection', 'cannot detect sound events', 'never detects sound events', 'no acoustic event detection', 'does not detect acoustic events', 'no siren detection', 'does not detect sirens', 'no gunshot detection', 'does not detect gunshots', 'no glass break detection', 'does not detect glass breaking', 'no baby cry detection', 'no dog bark detection', 'does not detect alarms', 'no alarm sound detection', 'without sound event recognition')


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'sound_event_detection_claim_audit', str(self.root), *args], capture_output=True, text=True)

    def test_phrase_oracle(self):
        tree = ast.parse(Path(phrases.__file__).read_text())
        parsed = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)}
        self.assertEqual(parsed['SOUND'], EXPECTED_SOUND)
        self.assertEqual(parsed['NOSOUND'], EXPECTED_NOSOUND)
        self.assertEqual(len(parsed['SOUND']), 42)
        self.assertEqual(len(parsed['NOSOUND']), 24)
        for phrase in EXPECTED_SOUND:
            self.assertEqual(phrases_in(phrase), {'SOUND'})
        for phrase in EXPECTED_NOSOUND:
            self.assertEqual(phrases_in(phrase), {'NOSOUND'})

    def test_good(self):
        self.put('README.md', 'sound event detection')
        self.put('app.py', 'model.detect_sound_event(audio)')
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_bad_exact(self):
        self.put('README.md', 'sound event detection')
        result = self.cli('--json')
        self.assertEqual(result.returncode, 2)
        report = json.loads(result.stdout)
        self.assertEqual(report['verdict'], 'FAIL')
        self.assertEqual(report['findings'][0]['id'], 'documented-sound-event-detection-claim-false')
        self.assertEqual(report['findings'][0]['severity'], 'HIGH')
        self.assertTrue(report['findings'][0]['message'])

    def test_test_only(self):
        self.put('README.md', 'sound event detection')
        self.put('tests/helper.py', 'model.detect_sound_event(audio)')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')
        self.assertEqual(self.cli().returncode, 0)
        self.assertEqual(self.cli('--fail-on', 'MEDIUM').returncode, 2)

    def test_denial(self):
        self.put('README.md', 'does not detect sound events')
        self.put('app.py', 'model.detect_sound_event(audio)')
        self.assertEqual(self.cli().returncode, 2)
        self.assertEqual(audit(self.root)['findings'][0]['id'], 'documented-no-sound-event-detection-claim-false')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')

    def test_no_claim(self):
        self.put('README.md', 'An application.')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_no_source_asymmetry(self):
        self.put('README.md', 'sound event detection')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')
        self.put('README.md', 'no sound event detection')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_fences_inline_normalization(self):
        for marker in ('```', '~~~'):
            for spaces in range(4):
                self.assertEqual(phrases_in(' ' * spaces + marker + '\nsound event detection\n' + ' ' * spaces + marker), set())
        self.assertEqual(phrases_in('`sound event detection`'), {'SOUND'})
        self.assertEqual(phrases_in("doesn't detect sound events"), {'NOSOUND'})
        self.assertEqual(phrases_in('SOUND-EVENT-DETECTION'), {'SOUND'})
        self.assertEqual(phrases_in('sound event\ndetection'), {'SOUND'})
        self.assertEqual(phrases_in('sound event\n\ndetection'), set())
        self.assertEqual(phrases_in('xsound event detectionx'), set())

    def test_docs_selection(self):
        self.put('nested/docs/a.md', 'sound event detection')
        self.assertTrue(audit(self.root)['findings'])
        self.assertEqual(audit(self.root, ['nested'])['verdict'], 'PASS')
        self.put('nested/docs/a.md', 'neutral')
        self.put('nested/README.md', 'sound event detection')
        self.assertEqual(audit(self.root)['verdict'], 'PASS')

    def test_exclusions(self):
        self.put('README.md', 'sound event detection')
        for path in ('fixtures/a.py', 'docs/a.py', 'examples/a.py'):
            self.put(path, 'm.detect_sound_event(a)')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')
        for path in ('test_one.py', 'one_test.py'):
            self.put(path, 'm.detect_sound_event(a)')
        self.assertEqual(audit(self.root)['findings'][0]['severity'], 'MEDIUM')

    def test_symlinks(self):
        self.put('README.md', 'sound event detection')
        with tempfile.TemporaryDirectory() as elsewhere:
            target = Path(elsewhere)
            (target / 'app.py').write_text('m.detect_sound_event(a)')
            (self.root / 'link.py').symlink_to(target / 'app.py')
            (self.root / 'linked').symlink_to(target, target_is_directory=True)
            self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')

    def test_split_pairs(self):
        self.put('README.md', 'sound event detection')
        for constructor, use in [('AudioTagging()', 'r.inference(a)'), ('YAMNet()', 'r(a)'), ('hub.load("yamnet")', 'r(a)')]:
            self.put('one.py', 'r = ' + constructor)
            self.put('two.py', use)
            self.assertEqual(audit(self.root)['findings'][0]['severity'], 'HIGH')

    def test_usage_version(self):
        self.assertEqual(self.cli('--version').stdout.strip(), '0.1.0')
        self.assertEqual(self.cli('--unknown').returncode, 1)
        self.assertEqual(self.cli('--fail-on', 'invalid').returncode, 1)
        result = subprocess.run([sys.executable, '-m', 'sound_event_detection_claim_audit'], capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(subprocess.run([sys.executable, '-m', 'sound_event_detection_claim_audit', str(self.root / 'missing')], capture_output=True).returncode, 1)

    def test_console_entry_definition(self):
        from importlib.metadata import distribution
        try:
            entries = distribution('sound-event-detection-claim-audit').entry_points
        except Exception:
            project = Path(__file__).resolve().parents[1] / 'pyproject.toml'
            self.assertIn('sound-event-detection-claim-audit = "sound_event_detection_claim_audit.audit:main"', project.read_text())
        else:
            self.assertTrue(any(e.name == 'sound-event-detection-claim-audit' and e.value == 'sound_event_detection_claim_audit.audit:main' for e in entries))



def route_test(source, expected):
    def test(self):
        self.assertEqual(evidence(source), expected, source)
    return test

setattr(AuditTests, 'test_positive_0', route_test('r=AudioTagging()\nr.inference(a)', True))
setattr(AuditTests, 'test_positive_1', route_test('from panns_inference import AudioTagging as A\nr=A()\nr.inference(a)', True))
setattr(AuditTests, 'test_positive_2', route_test('import panns_inference as p\nr=p.AudioTagging()\nr.inference(a)', True))
setattr(AuditTests, 'test_positive_3', route_test('r=hub.load("YAMNET/model")\nr(a)', True))
setattr(AuditTests, 'test_positive_4', route_test('from tensorflow_hub import load as L\nr=L("yamnet")\nr(a)', True))
setattr(AuditTests, 'test_positive_5', route_test('r=YAMNet()\nr(a)', True))
setattr(AuditTests, 'test_positive_6', route_test('from model import YAMNet as Y\nr: object=Y()\nr(a)', True))
setattr(AuditTests, 'test_positive_7', route_test('def pipeline(x,model): pass\npipeline("audio-classification", model="yamnet")', True))
setattr(AuditTests, 'test_positive_8', route_test('def load(x): pass\nr=load("yamnet")\nr(a)', True))
setattr(AuditTests, 'test_positive_9', route_test('pipeline("audio-classification", model="org/yamnet")', True))
setattr(AuditTests, 'test_positive_10', route_test('from transformers import pipeline as p\np("audio-classification", "org/yamnet")', True))
setattr(AuditTests, 'test_positive_11', route_test('pipeline("audio-classification", model="org/AST")', True))
setattr(AuditTests, 'test_positive_12', route_test('from transformers import pipeline as p\np("audio-classification", "org/AST")', True))
setattr(AuditTests, 'test_positive_13', route_test('pipeline("audio-classification", model="org/panns")', True))
setattr(AuditTests, 'test_positive_14', route_test('from transformers import pipeline as p\np("audio-classification", "org/panns")', True))
setattr(AuditTests, 'test_positive_15', route_test('pipeline("audio-classification", model="org/audioset")', True))
setattr(AuditTests, 'test_positive_16', route_test('from transformers import pipeline as p\np("audio-classification", "org/audioset")', True))
setattr(AuditTests, 'test_positive_17', route_test('obj.detect_sound_event(a)', True))
setattr(AuditTests, 'test_positive_18', route_test('from helper import detect_sound_event as f\nf(a)', True))
setattr(AuditTests, 'test_positive_19', route_test('from helper import detect_sound_event\ndetect_sound_event(a)', True))
setattr(AuditTests, 'test_positive_20', route_test('obj.detect_sound_events(a)', True))
setattr(AuditTests, 'test_positive_21', route_test('from helper import detect_sound_events as f\nf(a)', True))
setattr(AuditTests, 'test_positive_22', route_test('from helper import detect_sound_events\ndetect_sound_events(a)', True))
setattr(AuditTests, 'test_positive_23', route_test('obj.detect_audio_event(a)', True))
setattr(AuditTests, 'test_positive_24', route_test('from helper import detect_audio_event as f\nf(a)', True))
setattr(AuditTests, 'test_positive_25', route_test('from helper import detect_audio_event\ndetect_audio_event(a)', True))
setattr(AuditTests, 'test_positive_26', route_test('obj.detect_audio_events(a)', True))
setattr(AuditTests, 'test_positive_27', route_test('from helper import detect_audio_events as f\nf(a)', True))
setattr(AuditTests, 'test_positive_28', route_test('from helper import detect_audio_events\ndetect_audio_events(a)', True))
setattr(AuditTests, 'test_positive_29', route_test('obj.classify_sound_event(a)', True))
setattr(AuditTests, 'test_positive_30', route_test('from helper import classify_sound_event as f\nf(a)', True))
setattr(AuditTests, 'test_positive_31', route_test('from helper import classify_sound_event\nclassify_sound_event(a)', True))
setattr(AuditTests, 'test_positive_32', route_test('obj.classify_sound_events(a)', True))
setattr(AuditTests, 'test_positive_33', route_test('from helper import classify_sound_events as f\nf(a)', True))
setattr(AuditTests, 'test_positive_34', route_test('from helper import classify_sound_events\nclassify_sound_events(a)', True))
setattr(AuditTests, 'test_positive_35', route_test('obj.recognize_sound_event(a)', True))
setattr(AuditTests, 'test_positive_36', route_test('from helper import recognize_sound_event as f\nf(a)', True))
setattr(AuditTests, 'test_positive_37', route_test('from helper import recognize_sound_event\nrecognize_sound_event(a)', True))
setattr(AuditTests, 'test_positive_38', route_test('obj.recognise_sound_event(a)', True))
setattr(AuditTests, 'test_positive_39', route_test('from helper import recognise_sound_event as f\nf(a)', True))
setattr(AuditTests, 'test_positive_40', route_test('from helper import recognise_sound_event\nrecognise_sound_event(a)', True))
setattr(AuditTests, 'test_positive_41', route_test('obj.tag_sound_event(a)', True))
setattr(AuditTests, 'test_positive_42', route_test('from helper import tag_sound_event as f\nf(a)', True))
setattr(AuditTests, 'test_positive_43', route_test('from helper import tag_sound_event\ntag_sound_event(a)', True))
setattr(AuditTests, 'test_negative_0', route_test('import panns_inference', False))
setattr(AuditTests, 'test_negative_1', route_test('import tensorflow_hub', False))
setattr(AuditTests, 'test_negative_2', route_test('import transformers', False))
setattr(AuditTests, 'test_negative_3', route_test('vad.is_speech(a)', False))
setattr(AuditTests, 'test_negative_4', route_test('get_speech_timestamps(a)', False))
setattr(AuditTests, 'test_negative_5', route_test('pyannote.load("segmentation")', False))
setattr(AuditTests, 'test_negative_6', route_test('pvporcupine.create()', False))
setattr(AuditTests, 'test_negative_7', route_test('openwakeword.Model().predict(a)', False))
setattr(AuditTests, 'test_negative_8', route_test('snowboy.HotwordDetector()', False))
setattr(AuditTests, 'test_negative_9', route_test('obj.detect_keyword(a)', False))
setattr(AuditTests, 'test_negative_10', route_test('sb.verify_files(a,b)', False))
setattr(AuditTests, 'test_negative_11', route_test('resemblyzer.compare(a,b)', False))
setattr(AuditTests, 'test_negative_12', route_test('pipeline("speaker-verification")', False))
setattr(AuditTests, 'test_negative_13', route_test('obj.verify_speaker(a)', False))
setattr(AuditTests, 'test_negative_14', route_test('pipeline("diarization")', False))
setattr(AuditTests, 'test_negative_15', route_test('obj.diarize(a)', False))
setattr(AuditTests, 'test_negative_16', route_test('noisereduce.reduce_noise(a)', False))
setattr(AuditTests, 'test_negative_17', route_test('df.enhance(a)', False))
setattr(AuditTests, 'test_negative_18', route_test('obj.suppress_noise(a)', False))
setattr(AuditTests, 'test_negative_19', route_test('obj.remove_noise(a)', False))
setattr(AuditTests, 'test_negative_20', route_test('obj.transcribe(a)', False))
setattr(AuditTests, 'test_negative_21', route_test('obj.recognize_google(a)', False))
setattr(AuditTests, 'test_negative_22', route_test('obj.AcceptWaveform(a)', False))
setattr(AuditTests, 'test_negative_23', route_test('obj.stt(a)', False))
setattr(AuditTests, 'test_negative_24', route_test('langdetect.detect(a)', False))
setattr(AuditTests, 'test_negative_25', route_test('whisper.detect_language(a)', False))
setattr(AuditTests, 'test_negative_26', route_test('obj.translate(a)', False))
setattr(AuditTests, 'test_negative_27', route_test('translators.translate(a)', False))
setattr(AuditTests, 'test_negative_28', route_test('pyttsx3.say(a)', False))
setattr(AuditTests, 'test_negative_29', route_test('gTTS(a).save(b)', False))
setattr(AuditTests, 'test_negative_30', route_test('edge_tts.Communicate(a)', False))
setattr(AuditTests, 'test_negative_31', route_test('r.listen(a)', False))
setattr(AuditTests, 'test_negative_32', route_test('r.record(a)', False))
setattr(AuditTests, 'test_negative_33', route_test('sounddevice.rec(a)', False))
setattr(AuditTests, 'test_negative_34', route_test('stream.read(a)', False))
setattr(AuditTests, 'test_negative_35', route_test('obj.play(a)', False))
setattr(AuditTests, 'test_negative_36', route_test('librosa.load(a)', False))
setattr(AuditTests, 'test_negative_37', route_test('soundfile.read(a)', False))
setattr(AuditTests, 'test_negative_38', route_test('wave.read(a)', False))
setattr(AuditTests, 'test_negative_39', route_test('torchaudio.load(a)', False))
setattr(AuditTests, 'test_negative_40', route_test('pipeline("audio-classification")', False))
setattr(AuditTests, 'test_negative_41', route_test('pipeline("audio-classification",model="speech-emotion")', False))
setattr(AuditTests, 'test_negative_42', route_test('pipeline("audio-classification", "music-genre")', False))
setattr(AuditTests, 'test_negative_43', route_test('r=AudioTagging()', False))
setattr(AuditTests, 'test_negative_44', route_test('r=YAMNet()', False))
setattr(AuditTests, 'test_negative_45', route_test('r=hub.load("other")\nr(a)', False))
setattr(AuditTests, 'test_negative_46', route_test('r=hub.load("yamnet")', False))
setattr(AuditTests, 'test_negative_47', route_test('r.inference(a)', False))
setattr(AuditTests, 'test_negative_48', route_test('r.predict(a)', False))
setattr(AuditTests, 'test_negative_49', route_test('subprocess.run(["yamnet", "a.wav"])', False))
setattr(AuditTests, 'test_negative_50', route_test('s="yamnet AudioTagging inference"', False))
setattr(AuditTests, 'test_negative_51', route_test('obj.detect_sound_event', False))
setattr(AuditTests, 'test_negative_52', route_test('bad syntax !!!', False))
setattr(AuditTests, 'test_negative_53', route_test('r=Other()\nr.inference(a)', False))
setattr(AuditTests, 'test_negative_54', route_test('pipeline("text-classification", model="yamnet")', False))
setattr(AuditTests, 'test_negative_55', route_test('pipeline(task="audio-classification",model="yamnet")', False))
setattr(AuditTests, 'test_negative_56', route_test('pipeline("audio-classification",model=model)', False))
setattr(AuditTests, 'test_negative_57', route_test('r=hub.load(model)\nr(a)', False))
setattr(AuditTests, 'test_negative_58', route_test('def AudioTagging(): pass\nr=AudioTagging()\nr.inference(a)', False))
setattr(AuditTests, 'test_negative_59', route_test('from panns import AudioTagging as A\ndef A(): pass\nr=A()\nr.inference(a)', False))
setattr(AuditTests, 'test_negative_60', route_test('def YAMNet(): pass\nr=YAMNet()\nr(a)', False))
setattr(AuditTests, 'test_negative_61', route_test('detect_sound_event(a)', False))
setattr(AuditTests, 'test_negative_62', route_test('def detect_sound_event(a): pass\nobj.detect_sound_event(a)', False))
setattr(AuditTests, 'test_negative_63', route_test('from helper import detect_sound_event as f\ndef f(a): pass\nf(a)', False))
setattr(AuditTests, 'test_negative_64', route_test('class C:\n def detect_sound_event(self,a): pass\nobj.detect_sound_event(a)', False))
setattr(AuditTests, 'test_negative_65', route_test('detect_sound_events(a)', False))
setattr(AuditTests, 'test_negative_66', route_test('def detect_sound_events(a): pass\nobj.detect_sound_events(a)', False))
setattr(AuditTests, 'test_negative_67', route_test('from helper import detect_sound_events as f\ndef f(a): pass\nf(a)', False))
setattr(AuditTests, 'test_negative_68', route_test('class C:\n def detect_sound_events(self,a): pass\nobj.detect_sound_events(a)', False))
setattr(AuditTests, 'test_negative_69', route_test('detect_audio_event(a)', False))
setattr(AuditTests, 'test_negative_70', route_test('def detect_audio_event(a): pass\nobj.detect_audio_event(a)', False))
setattr(AuditTests, 'test_negative_71', route_test('from helper import detect_audio_event as f\ndef f(a): pass\nf(a)', False))
setattr(AuditTests, 'test_negative_72', route_test('class C:\n def detect_audio_event(self,a): pass\nobj.detect_audio_event(a)', False))
setattr(AuditTests, 'test_negative_73', route_test('detect_audio_events(a)', False))
setattr(AuditTests, 'test_negative_74', route_test('def detect_audio_events(a): pass\nobj.detect_audio_events(a)', False))
setattr(AuditTests, 'test_negative_75', route_test('from helper import detect_audio_events as f\ndef f(a): pass\nf(a)', False))
setattr(AuditTests, 'test_negative_76', route_test('class C:\n def detect_audio_events(self,a): pass\nobj.detect_audio_events(a)', False))
setattr(AuditTests, 'test_negative_77', route_test('classify_sound_event(a)', False))
setattr(AuditTests, 'test_negative_78', route_test('def classify_sound_event(a): pass\nobj.classify_sound_event(a)', False))
setattr(AuditTests, 'test_negative_79', route_test('from helper import classify_sound_event as f\ndef f(a): pass\nf(a)', False))
setattr(AuditTests, 'test_negative_80', route_test('class C:\n def classify_sound_event(self,a): pass\nobj.classify_sound_event(a)', False))
setattr(AuditTests, 'test_negative_81', route_test('classify_sound_events(a)', False))
setattr(AuditTests, 'test_negative_82', route_test('def classify_sound_events(a): pass\nobj.classify_sound_events(a)', False))
setattr(AuditTests, 'test_negative_83', route_test('from helper import classify_sound_events as f\ndef f(a): pass\nf(a)', False))
setattr(AuditTests, 'test_negative_84', route_test('class C:\n def classify_sound_events(self,a): pass\nobj.classify_sound_events(a)', False))
setattr(AuditTests, 'test_negative_85', route_test('recognize_sound_event(a)', False))
setattr(AuditTests, 'test_negative_86', route_test('def recognize_sound_event(a): pass\nobj.recognize_sound_event(a)', False))
setattr(AuditTests, 'test_negative_87', route_test('from helper import recognize_sound_event as f\ndef f(a): pass\nf(a)', False))
setattr(AuditTests, 'test_negative_88', route_test('class C:\n def recognize_sound_event(self,a): pass\nobj.recognize_sound_event(a)', False))
setattr(AuditTests, 'test_negative_89', route_test('recognise_sound_event(a)', False))
setattr(AuditTests, 'test_negative_90', route_test('def recognise_sound_event(a): pass\nobj.recognise_sound_event(a)', False))
setattr(AuditTests, 'test_negative_91', route_test('from helper import recognise_sound_event as f\ndef f(a): pass\nf(a)', False))
setattr(AuditTests, 'test_negative_92', route_test('class C:\n def recognise_sound_event(self,a): pass\nobj.recognise_sound_event(a)', False))
setattr(AuditTests, 'test_negative_93', route_test('tag_sound_event(a)', False))
setattr(AuditTests, 'test_negative_94', route_test('def tag_sound_event(a): pass\nobj.tag_sound_event(a)', False))
setattr(AuditTests, 'test_negative_95', route_test('from helper import tag_sound_event as f\ndef f(a): pass\nf(a)', False))
setattr(AuditTests, 'test_negative_96', route_test('class C:\n def tag_sound_event(self,a): pass\nobj.tag_sound_event(a)', False))

if __name__ == '__main__':
    unittest.main()
