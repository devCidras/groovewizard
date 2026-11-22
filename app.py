import sys

if __name__ == "__main__":
    if "--self-test" in sys.argv:  # CI: the packaged app starts and builds its window, then exits 0
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from organizador.gui import Window
        app = QApplication(sys.argv)
        w = Window()
        w.show()
        app.processEvents()
        print("self-test ok", flush=True)
        os._exit(0)  # skip Qt teardown: the check is that the app starts, and teardown order can crash headless
    from organizador.gui import main
    main()
