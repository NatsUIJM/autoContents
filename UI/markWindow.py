# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file '/Users/shijian/VSCode/autoContents/UI/markWindow.ui'
#
# Created by: PyQt5 UI code generator 5.15.11
#
# WARNING: Any manual changes made to this file will be lost when pyuic5 is
# run again.  Do not edit this file unless you know what you are doing.


from PyQt5 import QtCore, QtGui, QtWidgets


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(800, 1000)
        MainWindow.setMinimumSize(QtCore.QSize(800, 1000))
        MainWindow.setMaximumSize(QtCore.QSize(800, 1000))
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        self.verticalLayout = QtWidgets.QVBoxLayout(self.centralwidget)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout = QtWidgets.QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.addColumnBtn = QtWidgets.QPushButton(self.centralwidget)
        self.addColumnBtn.setMinimumSize(QtCore.QSize(0, 0))
        self.addColumnBtn.setObjectName("addColumnBtn")
        self.horizontalLayout.addWidget(self.addColumnBtn)
        self.addSectionBtn = QtWidgets.QPushButton(self.centralwidget)
        self.addSectionBtn.setObjectName("addSectionBtn")
        self.horizontalLayout.addWidget(self.addSectionBtn)
        self.deleteSectionBtn = QtWidgets.QPushButton(self.centralwidget)
        self.deleteSectionBtn.setObjectName("deleteSectionBtn")
        self.horizontalLayout.addWidget(self.deleteSectionBtn)
        self.addBanBtn = QtWidgets.QPushButton(self.centralwidget)
        self.addBanBtn.setObjectName("addBanBtn")
        self.horizontalLayout.addWidget(self.addBanBtn)
        self.deleteBanBtn = QtWidgets.QPushButton(self.centralwidget)
        self.deleteBanBtn.setObjectName("deleteBanBtn")
        self.horizontalLayout.addWidget(self.deleteBanBtn)
        self.verticalLayout.addLayout(self.horizontalLayout)
        self.graphicsView = QtWidgets.QGraphicsView(self.centralwidget)
        self.graphicsView.setMinimumSize(QtCore.QSize(8, 100))
        self.graphicsView.setMaximumSize(QtCore.QSize(780, 850))
        self.graphicsView.setObjectName("graphicsView")
        self.verticalLayout.addWidget(self.graphicsView)
        self.label = QtWidgets.QLabel(self.centralwidget)
        self.label.setObjectName("label")
        self.verticalLayout.addWidget(self.label)
        self.horizontalLayout_2 = QtWidgets.QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.prevPageBtn = QtWidgets.QPushButton(self.centralwidget)
        self.prevPageBtn.setObjectName("prevPageBtn")
        self.horizontalLayout_2.addWidget(self.prevPageBtn)
        self.nextPageBtn = QtWidgets.QPushButton(self.centralwidget)
        self.nextPageBtn.setObjectName("nextPageBtn")
        self.horizontalLayout_2.addWidget(self.nextPageBtn)
        self.verticalLayout.addLayout(self.horizontalLayout_2)
        MainWindow.setCentralWidget(self.centralwidget)

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "MainWindow"))
        self.addColumnBtn.setText(_translate("MainWindow", "添加分栏标记"))
        self.addSectionBtn.setText(_translate("MainWindow", "添加分节标记"))
        self.deleteSectionBtn.setText(_translate("MainWindow", "删除分节标记"))
        self.addBanBtn.setText(_translate("MainWindow", "添加分栏屏蔽"))
        self.deleteBanBtn.setText(_translate("MainWindow", "删除分栏屏蔽"))
        self.label.setText(_translate("MainWindow", "处理进度："))
        self.prevPageBtn.setText(_translate("MainWindow", "上一页"))
        self.nextPageBtn.setText(_translate("MainWindow", "下一页"))
