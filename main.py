# -*- coding: utf-8 -*-

import os
import sys
import threading

import wget
from PyQt5 import QtWidgets
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QUrl, QObject, pyqtSlot, pyqtSignal
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWebChannel import QWebChannel

from utils.utils import get_config, save_config
from utils.qiniu_api import get_buckets, get_bucket_domains, get_bucket_files, create_bucket, delete_bucket_file, \
    upload_bucket_file

web_view = None
ak = None
sk = None
cur_marker = ""
cur_prefix = ""
channel = None
handler = None
download_task = []


def get_abspath():
    try:
        root_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:  # We are the main py2exe script, not a module
        root_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    return root_dir


def init():
    global ak, sk, channel, handler

    # js -> python
    channel = QWebChannel()
    handler = CallHandler()
    channel.registerObject('handler', handler)
    web_view.page().setWebChannel(channel)
    # js -> python

    # 检查AccessKey和SecretKey
    ak, sk, _ = get_config()
    if ak is None:
        web_view.page().runJavaScript('show_setting_dialog();')
        return
    web_view.page().runJavaScript('set_keys("%s", "%s");' % (ak, sk))


def upload_file_succeed(name):
    web_view.page().runJavaScript('upload_file_succeed(' + '"' + name + '"' + ');')


def download_file(url, local_file):
    tmp_file = local_file + ".qiniu"

    def thread_download_file(url, tmp_file):
        tmp_file = wget.download(url, tmp_file)
        original_file = tmp_file[:tmp_file.rindex(".")]
        os.rename(tmp_file, original_file)

        # 更新文件下载状态，TODO 这里可能会crash，因为list并非是线程安全的
        global download_task
        for t in download_task:
            if t['url'] == url:
                t['status'] = 1
                break

    t = threading.Thread(target=thread_download_file, args=(url, tmp_file))
    t.start()


# js -> python
class CallHandler(QObject):
    result = pyqtSignal(int)

    @pyqtSlot(str, str, result=str)
    def save_keys(self, ak1, sk1):
        ak1 = ak1.replace(" ", "")
        ak1 = ak1.replace("\t", "")
        sk1 = sk1.replace(" ", "")
        sk1 = sk1.replace("\t", "")

        global ak, sk
        ak = ak1
        sk = sk1
        save_config(ak, sk, os.path.join(os.path.expanduser('~'), 'Desktop/'))
        return "save_keys. --by python."

    @pyqtSlot(result=str)
    def get_buckets(self):
        # 获取仓库列表
        ret, buckets = get_buckets(ak, sk)
        if ret is False:
            return "False"
        if buckets is None or len(buckets) == 0:
            return "True"

        result = ""
        for k in buckets:
            result += k + ";"
        if len(result) > 0:
            result = result[:-1]
        return "True" + result

    @pyqtSlot(str, result=str)
    def get_bucket_domains(self, bucket_name):
        # 获取仓库域名列表
        ret, domains = get_bucket_domains(ak, sk, bucket_name)
        if ret is False or domains is None or len(domains) == 0:
            return ""
        result = ""
        for k in domains:
            result += k + ";"
        if len(result) > 0:
            result = result[:-1]
        return result

    @pyqtSlot(str, str, str, result=str)
    def get_files(self, bucket_name, bucket_marker, bucket_prefix):
        ret, files = get_bucket_files(ak, sk, bucket_name, bucket_marker, 80, bucket_prefix)
        if ret is True:
            # 获取文件列表
            _files = ""
            if 'items' in files:
                for item in files['items']:
                    filename = item['key']
                    if bucket_prefix != "" and filename.startswith(bucket_prefix):
                        filename = filename[len(bucket_prefix):]
                    _files += '{"name":"%s", "size":%d, "timestamp":%d},' % (filename, item['fsize'], item['putTime'])
                if len(_files) > 0:
                    _files = _files[:-1]

            # 获取目录列表
            directories = ""
            if 'commonPrefixes' in files:
                for item in files['commonPrefixes']:
                    filename = item
                    if bucket_prefix != "" and filename.startswith(bucket_prefix):
                        filename = filename[len(bucket_prefix):]
                    directories += '"%s",' % filename
                if len(directories) > 0:
                    directories = directories[:-1]

            marker = ""
            if 'marker' in files:
                marker = files['marker']
            return '{"status":0, "files":[%s], "directories":[%s], "marker":"%s"}' % (_files, directories, marker)
        else:
            return '{"status":-1}'

    @pyqtSlot(str, result=str)
    def create_bucket(self, bucket_name):
        ret, result = create_bucket(ak, sk, bucket_name)
        if ret is True:
            return "True"
        return str(result)

    @pyqtSlot(str, result=str)
    def copy_url(self, url):
        QtWidgets.QApplication.clipboard().setText(url)
        return "True"

    @pyqtSlot(str, result=str)
    def download_url(self, url):
        global download_task

        # 判断此任务是否已经存在
        for t in download_task:
            if t['url'] == url:
                return "False"

        # 截取文件名，拼接出本地文件路径
        file_name = url.split("/")[-1]
        _, _, save_dir = get_config()
        save_file = save_dir + file_name

        # 添加到任务列表
        download_task.append({"url": url, "file": save_file, "status": 0})
        download_file(url, save_file)
        return "True"

    @pyqtSlot(str, str, result=str)
    def delete_url(self, bucket, file):
        ret, result = delete_bucket_file(ak, sk, bucket, file)
        if ret is True:
            return "True"
        return str(result)

    @pyqtSlot(str, str, str, str, result=str)
    def upload_file_data(self, bucket, prefix, name, data):
        binary_data = bytearray()
        binary_data.extend(map(ord, data))
        upload_bucket_file(ak, sk, bucket, prefix, name, binary_data, upload_file_succeed)
        return "True"


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QIcon("favicon.ico"))
    web = QWebEngineView()
    web.setWindowTitle("七牛个人网盘 v1.0")
    web.loadFinished.connect(init)
    web.load(QUrl.fromLocalFile(get_abspath() + "/html/index.html"))
    web.show()
    web_view = web
    sys.exit(app.exec())
