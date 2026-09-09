import time

from utils.music.audio_buffer import BufferedPCMAudio


class FakePCMSource:
    def __init__(self, frames, *, delay=0.0):
        self.frames = list(frames)
        self.delay = delay
        self.cleaned = False

    def read(self):
        if self.delay:
            time.sleep(self.delay)
        if not self.frames:
            return b""
        return self.frames.pop(0)

    def is_opus(self):
        return False

    def cleanup(self):
        self.cleaned = True


def test_buffer_preserves_frame_order_and_eof():
    source = FakePCMSource([b"a", b"b", b"c"])
    buffered = BufferedPCMAudio(
        source,
        prebuffer_seconds=0.02,
        max_buffer_seconds=0.20,
        startup_timeout=1.0,
        label="test",
    )
    assert buffered.read() == b"a"
    assert buffered.read() == b"b"
    assert buffered.read() == b"c"
    assert buffered.read() == b""
    buffered.cleanup()
    assert source.cleaned is True


def test_cleanup_is_idempotent():
    source = FakePCMSource([b"a"])
    buffered = BufferedPCMAudio(
        source,
        prebuffer_seconds=0.02,
        max_buffer_seconds=0.20,
        startup_timeout=1.0,
    )
    buffered.cleanup()
    buffered.cleanup()
    assert source.cleaned is True
    assert buffered.read() == b""


def test_buffer_can_read_ahead_from_slowish_source():
    source = FakePCMSource([b"a", b"b", b"c", b"d"], delay=0.005)
    buffered = BufferedPCMAudio(
        source,
        prebuffer_seconds=0.04,
        max_buffer_seconds=0.20,
        startup_timeout=1.0,
    )
    assert buffered.read() == b"a"
    assert buffered.buffered_seconds >= 0.0
    assert buffered.read() == b"b"
    buffered.cleanup()
