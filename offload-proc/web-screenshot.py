import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QUrl, QTimer
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings

class Screenshot(QWebEngineView):
    def __init__(self, url, wait_ms, out_file):
        self.app = QApplication(['Web Screenshot'])
        super(Screenshot, self).__init__()
        self.url = url
        self.wait_ms = wait_ms
        self.out_file = out_file

    def capture(self):
        self.load(QUrl(self.url))
        self.loadFinished.connect(self.on_loaded)
        # Create hidden view without scrollbars
        self.setAttribute(Qt.WA_DontShowOnScreen)
        self.page().settings().setAttribute(
            QWebEngineSettings.ShowScrollBars, False)
        self.show()

    def on_loaded(self):
        size = self.page().contentsSize().toSize() * 1.01
        self.resize(size)
        QTimer.singleShot(self.wait_ms, self.take_screenshot)

    def take_screenshot(self):
        self.grab().save(self.out_file, b'PNG')
        self.page().profile().clearHttpCache()
        self.app.quit()

s = Screenshot(sys.argv[1], int(sys.argv[2]), sys.argv[3])
s.capture()
sys.exit(s.app.exec_())
