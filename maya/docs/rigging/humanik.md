# HumanIK Auto Setup

選択したJoint階層から、限定的なHumanIK Characterを作成します。

## Reference

- **Menu:** `YWTA > Rigging > HumanIK Auto Setup`
- **Selection:** CharacterのRoot Joint

## Usage

Root Jointを選択して実行します。処理は階層からHipまたはPelvisを探し、HumanIK Characterへ
割り当ててLockします。

## Known Limitations

汎用的な全身自動マッピングではありません。Hip / Pelvis中心の限定的な設定で、Character名も
固定されています。

現在は、PyMELが見つからず起動できない環境があります。依存関係が解決していることを確認し、
保存済みSceneのコピーで使用してください。
