"""Shared compact desktop theme, including the inline editing tools."""
def apply_theme(app):
    app.setStyleSheet('''
        QWidget {font-family:"Malgun Gothic";font-size:12px;color:#253348;}
        QMainWindow, QDialog {background:#f2f5f9;}
        QWidget#header {background:#f2f5f9;}
        QLabel {background:transparent;}
        QLabel#imageTitle {font-weight:600;color:#172b46;padding:2px 0;}
        QPushButton, QToolButton {background:#ffffff;border:1px solid #d7dfe9;
            border-radius:5px;padding:4px 9px;min-height:20px;}
        QPushButton:hover, QToolButton:hover {background:#edf4ff;border-color:#94b6e6;}
        QPushButton:pressed, QToolButton:pressed {background:#dce9fb;}
        QPushButton:checked, QToolButton:checked {background:#e0edff;border-color:#6799dc;color:#1855a5;}
        QPushButton:disabled, QToolButton:disabled {background:#f3f5f8;color:#a1acba;border-color:#e1e6ee;}
        QPushButton:focus {border-color:#4e8cd9;}
        QPushButton#primaryButton {background:#2867bf;border-color:#2867bf;color:white;font-weight:600;}
        QPushButton#primaryButton:hover {background:#2058a5;}
        QPushButton#primaryButton:disabled {background:#9bb5d8;border-color:#9bb5d8;}
        QWidget#toolPicker QToolButton {padding:0;min-height:0;}
        QLineEdit, QSpinBox, QComboBox {background:white;border:1px solid #d4ddea;
            border-radius:4px;padding:3px 6px;min-height:20px;selection-background-color:#d2e4ff;selection-color:#163b70;}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {border-color:#508bd7;}
        QComboBox::drop-down {border:0;width:18px;}
        QCheckBox {spacing:5px;padding:2px;}
        QCheckBox::indicator {width:13px;height:13px;}
        QListWidget {background:#ffffff;border:1px solid #dce3ed;border-radius:6px;outline:0;}
        QListWidget::item {border-radius:4px;}
        QListWidget::item:hover {background:#f0f5fc;}
        QListWidget::item:selected {background:#e1edff;color:#174e96;}
        QListWidget#projectList {padding:4px;}
        QListWidget#projectList::item {padding:0 7px;}
        QListWidget#thumbnailList {background:#202936;color:#e6edf7;}
        QListWidget#thumbnailList::item:hover {background:#202936;color:#e6edf7;}
        QListWidget#thumbnailList::item:selected, QListWidget#thumbnailList::item:selected:hover {background:#354e70;color:white;}
        QDockWidget {font-weight:600;}
        QDockWidget::title {background:#e7edf5;padding:7px 9px;border-radius:4px;}
        QScrollArea {border:0;background:transparent;}
        QScrollBar:vertical {background:#eef2f7;width:10px;margin:0;}
        QScrollBar:horizontal {background:#eef2f7;height:10px;margin:0;}
        QScrollBar::handle {background:#bcc9d9;border-radius:4px;min-height:24px;min-width:24px;}
        QScrollBar::handle:hover {background:#91a8c3;}
        QScrollBar::add-line, QScrollBar::sub-line {width:0;height:0;}
        QScrollBar::add-page, QScrollBar::sub-page {background:transparent;}
        QMenu {background:white;border:1px solid #d4ddea;padding:4px;}
        QMenu::item {padding:6px 20px;border-radius:3px;}
        QMenu::item:selected {background:#e4efff;}
        QToolTip {background:#23364f;color:white;border:0;padding:6px;}
        QProgressBar {border:0;background:#e0e7f0;border-radius:4px;text-align:center;}
        QProgressBar::chunk {background:#4b86d2;border-radius:4px;}
    ''')


def action_icon(kind):
    from PySide6.QtCore import Qt, QRectF
    from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QIcon, QPainterPath
    pix=QPixmap(32,32);pix.setDevicePixelRatio(2);pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor('#526781'),1.3,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    if kind=='folder':
        path=QPainterPath();path.moveTo(2,5);path.lineTo(2,3);path.lineTo(6,3);path.lineTo(8,5);path.lineTo(14,5);path.lineTo(14,13);path.lineTo(2,13);path.closeSubpath();p.drawPath(path)
    elif kind=='save':
        p.drawRoundedRect(QRectF(2,2,12,12),1,1);p.drawRect(5,2,6,4);p.drawRect(5,9,6,5)
    elif kind=='trash':
        p.drawLine(2,4,14,4);p.drawLine(6,2,10,2);p.drawLine(4,5,5,14);p.drawLine(5,14,11,14);p.drawLine(11,14,12,5);p.drawLine(7,7,7,11);p.drawLine(9,7,9,11)
    elif kind in ('undo','redo'):
        if kind=='redo':p.translate(16,0);p.scale(-1,1)
        path=QPainterPath();path.moveTo(3,7);path.cubicTo(13,3,15,10,11,13);p.drawPath(path);p.drawLine(3,7,3,3);p.drawLine(3,7,7,8)
    else:
        p.drawRoundedRect(QRectF(3,2,10,12),1,1);p.drawLine(6,6,10,6);p.drawLine(6,9,10,9)
    p.end();return QIcon(pix)
