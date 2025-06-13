"""
Maya内でのユニットテストプロセスを支援する関数とクラスを提供します。

主要なクラス：
TestCase - unittest.TestCaseを継承し、プラグインの自動ロード/アンロード、一時ファイル名の生成と
           クリーンアップなどの便利な機能を追加したクラスです。
TestResult - unittest.TextTestResultを継承し、各テスト間での新規ファイル作成やスクリプトエディタの
            出力抑制などのカスタマイズを行うクラスです。

このシステムでテストを作成するにはtestsディレクトリ内に新規のPythonファイルを作成し、以下の手順に従います：
    a) YWTA.test.TestCaseを継承したクラスを作成
    b) unittestモジュールのassertメソッドを使用して結果を検証するテストを1つ以上作成

使用例：

# test_sample.py
from ywta.test import TestCase
class SampleTests(TestCase):
    def test_create_sphere(self):
        sphere = cmds.polySphere(n='mySphere')[0]
        self.assertEqual('mySphere', sphere)

# Mayaで特定のテストケースのみを実行
import ywta.test
ywta.test.run_tests(test='test_sample.SampleTests')

# テストケース内の特定のテストを実行
ywta.test.run_tests(test='test_sample.SampleTests.test_create_sphere')

# すべてのテストを実行
ywta.test.run_tests()
"""

import os
import shutil
import sys
import unittest
import tempfile
import uuid
import logging
import maya.cmds as cmds

# The environment variable that signifies tests are being run with the custom TestResult class.
YWTA_TESTING_VAR = "YWTA_UNITTEST"


def run_tests(test=None, test_suite=None):
    """指定されたパスにあるすべてのテストを実行します。

    @param test: 実行する特定のテストの名前（オプション）。
    @param test_suite: 実行するTestSuite（オプション）。省略された場合、TestSuiteが生成されます。
    """
    if test_suite is None:
        test_suite = get_tests(test)

    runner = unittest.TextTestRunner(verbosity=2, resultclass=TestResult)
    runner.failfast = False
    runner.buffer = Settings.buffer_output
    runner.run(test_suite)


def get_tests(test=None, test_suite=None):
    """必要なすべてのテストを含むunittest.TestSuiteを取得します。

    MAYA_MODULE_PATHにある全モジュールの「tests」ディレクトリを使用します。
    @param test: 'test_mytest.SomeTestCase.test_function'のような特定のテストを見つけるためのテストパス（オプション）。
    @param test_suite: 発見されたテストを追加するunittest.TestSuite（オプション）。省略された場合、新しいTestSuiteが
    作成されます。
    @return: テストが追加されたTestSuite。
    """

    # maya/ywta/testsディレクトリから探す
    directories = [os.path.join(os.path.dirname(__file__), "../tests")]

    # Populate a TestSuite with all the tests
    if test_suite is None:
        test_suite = unittest.TestSuite()

    if test:
        # Find the specified test to run
        directories_added_to_path = [p for p in directories if add_to_path(p)]
        discovered_suite = unittest.TestLoader().loadTestsFromName(test)
        if discovered_suite.countTestCases():
            test_suite.addTests(discovered_suite)
    else:
        # Find all tests to run
        directories_added_to_path = []
        for p in directories:
            discovered_suite = unittest.TestLoader().discover(p)
            if discovered_suite.countTestCases():
                test_suite.addTests(discovered_suite)

    # Remove the added paths.
    for path in directories_added_to_path:
        sys.path.remove(path)

    return test_suite


def run_tests_from_commandline():
    """Mayaスタンドアロンモードでテストを実行します。

    コマンドラインからYWTA/bin/runmayatests.pyを実行する際に呼び出されます。
    """
    import maya.standalone

    maya.standalone.initialize()

    # Make sure all paths in PYTHONPATH are also in sys.path
    # When a maya module is loaded, the scripts folder is added to PYTHONPATH, but it doesn't seem
    # to be added to sys.path. So we are unable to import any of the python files that are in the
    # module/scripts folder. To workaround this, we simply add the paths to sys ourselves.
    realsyspath = [os.path.realpath(p) for p in sys.path]
    pythonpath = os.environ.get("PYTHONPATH", "")
    for p in pythonpath.split(os.pathsep):
        p = os.path.realpath(p)  # Make sure symbolic links are resolved
        if p not in realsyspath:
            sys.path.insert(0, p)

    run_tests()

    # Starting Maya 2016, we have to call uninitialize
    if float(cmds.about(v=True)) >= 2016.0:
        maya.standalone.uninitialize()


class Settings(object):
    """テスト実行のためのオプションを含むクラス。"""

    # Specifies where files generated during tests should be stored
    # Use a uuid subdirectory so tests that are running concurrently such as on a build server
    # do not conflict with each other.
    temp_dir = os.path.join(tempfile.gettempdir(), "mayaunittest", str(uuid.uuid4()))

    # Controls whether temp files should be deleted after running all tests in the test case
    delete_files = True

    # Specifies whether the standard output and standard error streams are buffered during the test run.
    # Output during a passing test is discarded. Output is echoed normally on test fail or error and is
    # added to the failure messages.
    buffer_output = True

    # Controls whether we should do a file new between each test case
    file_new = True


def set_temp_dir(directory):
    """テストから生成されたファイルを保存する場所を設定します。

    @param directory: ディレクトリパス。
    """
    if os.path.exists(directory):
        Settings.temp_dir = directory
    else:
        raise RuntimeError("{0} does not exist.".format(directory))


def set_delete_files(value):
    """テストケース内のすべてのテスト実行後に一時ファイルを削除するかどうかを設定します。

    @param value: TestCaseに登録されたファイルを削除する場合はTrue。
    """
    Settings.delete_files = value


def set_buffer_output(value):
    """テスト実行中に標準出力と標準エラーストリームをバッファリングするかどうかを設定します。

    @param value: TrueまたはFalse
    """
    Settings.buffer_output = value


def set_file_new(value):
    """各テスト後に新しいファイルを作成するかどうかを設定します。

    @param value: TrueまたはFalse
    """
    Settings.file_new = value


def add_to_path(path):
    """指定されたパスをシステムパスに追加します。

    @param path: 追加するパス。
    @return パスが追加された場合はTrue。パスが存在しないか、すでにsys.pathにある場合はFalseを返します。
    """
    if os.path.exists(path) and path not in sys.path:
        sys.path.insert(0, path)
        return True
    return False


class TestCase(unittest.TestCase):
    """Maya内で実行されるユニットテストケースの基本クラス。

    テストはこのTestCaseを継承する必要はありませんが、このクラスにはプラグインのロード/アンロードや
    一時ファイルのクリーンアップなどの便利な機能が含まれています。
    """

    # Keep track of all temporary files that were created so they can be cleaned up after all tests have been run
    files_created = []

    # Keep track of which plugins were loaded so we can unload them after all tests have been run
    plugins_loaded = set()

    @classmethod
    def tearDownClass(cls):
        unittest.TestCase.tearDownClass()
        cls.delete_temp_files()
        cls.unload_plugins()

    @classmethod
    def load_plugin(cls, plugin):
        """指定されたプラグインをロードし、TestCase終了時にアンロードするために保存します。

        @param plugin: プラグイン名。
        """
        cmds.loadPlugin(plugin, qt=True)
        cls.plugins_loaded.add(plugin)

    @classmethod
    def unload_plugins(cls):
        # このテストケースでロードされたプラグインをアンロード
        for plugin in cls.plugins_loaded:
            cmds.unloadPlugin(plugin)
        cls.plugins_loaded = []

    @classmethod
    def delete_temp_files(cls):
        """キャッシュ内の一時ファイルを削除し、キャッシュをクリアします。"""
        # デバッグ目的で一時ファイルを保持したくない場合、このTestCaseのすべてのテストが
        # 実行された後にファイルを削除します
        if Settings.delete_files:
            for f in cls.files_created:
                if os.path.exists(f):
                    os.remove(f)
            cls.files_create = []
            if os.path.exists(Settings.temp_dir):
                shutil.rmtree(Settings.temp_dir)

    @classmethod
    def get_temp_filename(cls, file_name):
        """テストディレクトリ内の一意のファイルパス名を取得します。

        ファイルは作成されません。作成は呼び出し元の責任です。このファイルはテスト終了時に削除されます。
        @param file_name: 部分的なパス例：'directory/somefile.txt'
        @return 一時ファイルへのフルパス。
        """
        temp_dir = Settings.temp_dir
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        base_name, ext = os.path.splitext(file_name)
        path = "{0}/{1}{2}".format(temp_dir, base_name, ext)
        count = 0
        while os.path.exists(path):
            # If the file already exists, add an incrememted number
            count += 1
            path = "{0}/{1}{2}{3}".format(temp_dir, base_name, count, ext)
        cls.files_created.append(path)
        return path

    def assertListAlmostEqual(self, first, second, places=7, msg=None, delta=None):
        """浮動小数点値のリストがほぼ等しいことをアサートします。

        unittestにはassertAlmostEqualとassertListEqualはありますが、assertListAlmostEqualはありません。
        """
        self.assertEqual(len(first), len(second), msg)
        for a, b in zip(first, second):
            self.assertAlmostEqual(a, b, places, msg, delta)

    def tearDown(self):
        if Settings.file_new and YWTA_TESTING_VAR not in os.environ.keys():
            # PyCharmなどのカスタムランナーなしでテストを実行する場合、TestResultクラスのfile newは
            # 使用されないため、ここでfile newを呼び出します
            cmds.file(f=True, new=True)


class TestResult(unittest.TextTestResult):
    """各テスト間での新規ファイル作成やスクリプトエディタの出力抑制などを行うためにテスト結果をカスタマイズします。"""

    def __init__(self, stream, descriptions, verbosity):
        super(TestResult, self).__init__(stream, descriptions, verbosity)
        self.successes = []

    def startTestRun(self):
        """テスト実行前に呼び出されます。"""
        super(TestResult, self).startTestRun()
        # カスタムランナーを通じてテストが実行されていることを指定する環境変数を作成します。
        os.environ[YWTA_TESTING_VAR] = "1"

        ScriptEditorState.suppress_output()
        if Settings.buffer_output:
            # テスト実行中のログを無効にします。criticalを無効にすることで、
            # critical以下のすべてのレベルのログも無効になります
            logging.disable(logging.CRITICAL)

    def stopTestRun(self):
        """すべてのテスト実行後に呼び出されます。"""
        if Settings.buffer_output:
            # ログ状態を復元
            logging.disable(logging.NOTSET)
        ScriptEditorState.restore_output()
        if Settings.delete_files and os.path.exists(Settings.temp_dir):
            shutil.rmtree(Settings.temp_dir)

        del os.environ[YWTA_TESTING_VAR]

        super(TestResult, self).stopTestRun()

    def stopTest(self, test):
        """個々のテスト実行後に呼び出されます。

        @param test: 実行されたばかりのTestCase。"""
        super(TestResult, self).stopTest(test)
        if Settings.file_new:
            cmds.file(f=True, new=True)

    def addSuccess(self, test):
        """成功したテストのリストを保存できるように、基本のaddSuccessメソッドをオーバーライドします。

        @param test: 正常に実行されたTestCase。"""
        super(TestResult, self).addSuccess(test)
        self.successes.append(test)


class ScriptEditorState(object):
    """スクリプトエディタの出力を抑制および復元するメソッドを提供します。"""

    # Used to restore logging states in the script editor
    suppress_results = None
    suppress_errors = None
    suppress_warnings = None
    suppress_info = None

    @classmethod
    def suppress_output(cls):
        """すべてのスクリプトエディタ出力を非表示にします。"""
        if Settings.buffer_output:
            cls.suppress_results = cmds.scriptEditorInfo(q=True, suppressResults=True)
            cls.suppress_errors = cmds.scriptEditorInfo(q=True, suppressErrors=True)
            cls.suppress_warnings = cmds.scriptEditorInfo(q=True, suppressWarnings=True)
            cls.suppress_info = cmds.scriptEditorInfo(q=True, suppressInfo=True)
            cmds.scriptEditorInfo(
                e=True,
                suppressResults=True,
                suppressInfo=True,
                suppressWarnings=True,
                suppressErrors=True,
            )

    @classmethod
    def restore_output(cls):
        """スクリプトエディタの出力設定を元の値に復元します。"""
        if None not in {
            cls.suppress_results,
            cls.suppress_errors,
            cls.suppress_warnings,
            cls.suppress_info,
        }:
            cmds.scriptEditorInfo(
                e=True,
                suppressResults=cls.suppress_results,
                suppressInfo=cls.suppress_info,
                suppressWarnings=cls.suppress_warnings,
                suppressErrors=cls.suppress_errors,
            )


if __name__ == "__main__":
    run_tests_from_commandline()
