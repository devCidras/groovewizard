import sys


def check_bpm():
    """The audio libraries are in the package and work: a click at 125 BPM measures 125."""
    import os
    import tempfile
    import wave
    from organizador import bpm
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "clique ç.wav")
        with wave.open(p, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(44100)
            w.writeframes((b"\xff\x3f\x01\xc0" * 300 + bytes(44100 * 60 // 125 * 2 - 1200)) * 100)
        measured = bpm.measure(p)
        if measured != 125:
            raise RuntimeError(f"BPM: {measured}")
        # Exercise the packaged player and codec without depending on speakers in CI.
        from PySide6.QtCore import QEventLoop, QTimer, QUrl
        from PySide6.QtMultimedia import QAudioBufferOutput, QMediaPlayer
        player, output = QMediaPlayer(), QAudioBufferOutput()
        player.setAudioBufferOutput(output)
        loop = QEventLoop()
        decoded = []

        def got_buffer(buffer):
            if buffer.frameCount():
                decoded.append(buffer.frameCount())
                loop.quit()

        output.audioBufferReceived.connect(got_buffer)
        player.errorOccurred.connect(loop.quit)
        timeout = QTimer(singleShot=True, interval=10000)
        timeout.timeout.connect(loop.quit)
        timeout.start()
        player.setSource(QUrl.fromLocalFile(p))
        player.play()
        if not decoded and not player.errorString():
            loop.exec()
        error = player.errorString()
        player.stop()
        player.setSource(QUrl())
        if not decoded:
            raise RuntimeError(f"Audio preview: {error or 'no decoded audio'}")


def self_test():
    """CI / installer check: the (packaged) app starts and builds its window. Result also goes to
    groovewizard-self-test.log, because a windowed .exe has no console (sys.stdout is None)."""
    import os
    import traceback
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    log = os.path.join(os.getcwd(), "groovewizard-self-test.log")
    app = w = None
    try:
        from PySide6.QtWidgets import QApplication
        from organizador.gui import Window
        app = QApplication(sys.argv)
        w = Window()
        w.show()
        app.processEvents()
        check_bpm()
        result, code = "self-test ok", 0
    except Exception:
        result, code = traceback.format_exc(), 1
    finally:
        if w is not None:
            w.close()
        if app is not None:
            app.quit()
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(result + "\n")
    if sys.stdout:
        print(result, flush=True)
    return code


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    from organizador.gui import main
    main()
