import sys


def self_test():
    """CI / installer check: the (packaged) app starts and builds its window. Result also goes to
    groovewizard-self-test.log, because a windowed .exe has no console (sys.stdout is None)."""
    import os
    import traceback
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    log = os.path.join(os.getcwd(), "groovewizard-self-test.log")
    try:
        from PySide6.QtWidgets import QApplication
        from organizador.gui import Window
        app = QApplication(sys.argv)
        w = Window()
        w.show()
        app.processEvents()
        result, code = "self-test ok", 0
    except Exception:
        result, code = traceback.format_exc(), 1
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(result + "\n")
    if sys.stdout:
        print(result, flush=True)
    # skip Qt teardown entirely (its DLL unload can crash headless and turn a pass into a failure)
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.TerminateProcess(k32.GetCurrentProcess(), code)
    except Exception:
        pass
    os._exit(code)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    from organizador.gui import main
    main()
