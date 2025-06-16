# YWTA Tools - Cline Rules
# Maya/Blender用テクニカルアーティストツール開発プロジェクト

## プロジェクト概要
- MayaとBlender用のテクニカルアーティストツール集
- Python/C++によるプラグイン開発
- リギング、デフォーメーション、アニメーション、メッシュ処理ツール

## 開発環境とツール
- Maya 2024対応
- Blender アドオン開発
- Visual Studio + CMake (C++プラグイン用)
- Python 3.x

## コーディング規約

### 一般規約
- コードは読みやすく、保守性を重視
- コメントは適切に記述
- シンプルかつ必要最低限な実装を意識し、長いコードや複雑なロジックは避ける。

### Python
- PEP 8に準拠
- Maya Python API 2.0を優先使用
- docstringは必須（Google形式推奨）
- 型ヒントの使用を推奨
- インデント: 4スペース

### C++
- .clang-formatファイルに従う
- Maya C++ APIの使用
- CMakeによるビルド設定

### ファイル構成
- maya/ywta/: Pythonモジュール
- maya/cpp/: C++プラグインソース
- blender/addons/: Blenderアドオン
- maya/icons/: UIアイコン
- maya/plug-ins/: コンパイル済みプラグイン

## 開発ルール

### 新機能追加時
1. 適切なサブモジュールに配置（rig/, deform/, mesh/, anim/等）
2. menu.pyにメニューエントリを追加
3. 必要に応じてアイコンを作成
4. テストコードの作成（maya/ywta/test/）

### ファイル変更時の注意
- userSetup.pyの変更は慎重に（Maya起動時に実行される）
- .modファイルの変更時はパス設定を確認
- C++プラグインの変更時はbuild.batでリビルド必要

### UI開発
- Maya標準UIコンポーネントを使用
- PySide2/PyQt5の使用も可
- アイコンは maya/icons/ に配置
- メニュー構造は既存パターンに従う

### テスト
- maya_unit_testui.pyを使用したユニットテスト
- 新機能には対応するテストを作成
- Maya環境でのテスト実行を前提

## 依存関係
- numpy, scipy, pyparsing (requirements.txt参照)　（新しいPythonモジュールは追加しないこと
- Maya Python API
- Blender Python API
- Visual Studio (C++開発時)

## ビルドとデプロイ
- C++プラグイン: maya/cpp/build.bat実行
- Mayaモジュール: MAYA_MODULE_PATHに配置
- Blenderアドオン: 標準的なアドオンインストール手順

## 禁止事項
- Maya/Blenderの安定性を損なう可能性のあるコード
- ライセンス違反となるコードの使用
- 外部依存関係の無断追加

## 推奨事項
- 既存コードパターンの踏襲
- エラーハンドリングの適切な実装
- ユーザビリティを考慮したUI設計
- パフォーマンスを意識した実装

## ファイル変更時の確認事項
- 関連するテストの実行
- メニュー構造の整合性確認
- 依存関係の影響範囲確認
- ドキュメントの更新
