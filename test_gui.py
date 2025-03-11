import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QLabel, QVBoxLayout, QWidget

class TestWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt6 Test Window")
        self.setGeometry(100, 100, 400, 200)
        
        layout = QVBoxLayout()
        
        label = QLabel("This is a test PyQt6 window")
        button = QPushButton("Click Me")
        button.clicked.connect(self.on_button_click)
        
        layout.addWidget(label)
        layout.addWidget(button)
        
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)
    
    def on_button_click(self):
        print("Button clicked!")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec()) 