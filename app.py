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
