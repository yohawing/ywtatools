# Unit Test Runner

YWTAのUnit、Integration、Performance TestをMaya内から実行します。

## Reference

- **Menu:** `YWTA > Utility > Unit Test Runner`
- **Audience:** YWTA開発者

## Usage

Testを選択し、`Run Selected Tests`または`Run All Tests`を実行します。実行後はTest件数が
0でないことと、Pass、Fail、Error、Skippedを確認します。

## Warning

`New Scene Between Test`は既定で有効です。各Testの後に新規Sceneを作るため、未保存の
制作Sceneを失う可能性があります。制作中のMayaでは開かず、専用のMaya Sessionで使用して
ください。
