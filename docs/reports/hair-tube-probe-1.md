# HAIR-TUBE-PROBE-1 診断結果

## 結論

2026-08-13 に、ローカルの実髪 GLB corpusから5件を選び、元ファイルへ書き込まない
read-only probeを実行した。今回の5件では、4-sided quad tubeを証明できた候補は
`0 / 5`（0%）だった。

この結果は「髪が4-sided tubeではない」と断定するものではない。GLBが全身を1 mesh・1
primitiveへflattenしており、mesh/node/material名にも髪のsemanticが無く、さらに
primitive modeが全件 `TRIANGLES` だったため、髪部分のroot loop、quad面、railを
安全に分離できなかった、という fail-closed の結果である。したがって現時点では
4-rail MVPを一般のGLB髪へ無条件に適用せず、DCC上で髪objectまたはroot loopを明示的に
選択できる入力経路を先に用意するべきである。

## 対象と再現コマンド

対象は再配布しないローカル診断資料であり、リポジトリへコピーしていない。
ファイル名を髪付きモデルの選択manifestとして使い、GLB内の名前から髪であると推測して
いない。

```text
F:\3dcg\idea\glb\LumiMagical.glb
F:\3dcg\idea\glb\カラフルヘアガール顔.glb
F:\3dcg\idea\glb\桃髪ガールダンス付き.glb
F:\3dcg\idea\glb\照れ前髪ガール.glb
F:\3dcg\idea\glb\雨に濡れた少女.glb
```

```powershell
python tools/hair_tube_probe.py `
  F:\3dcg\idea\glb\LumiMagical.glb `
  F:\3dcg\idea\glb\カラフルヘアガール顔.glb `
  F:\3dcg\idea\glb\桃髪ガールダンス付き.glb `
  F:\3dcg\idea\glb\照れ前髪ガール.glb `
  F:\3dcg\idea\glb\雨に濡れた少女.glb
```

probeはGLBをread-onlyで開き、JSON chunkだけを解釈してBIN chunkのgeometryは復元しない。
実髪の個別componentを
証明できない場合、root/tip、cap、pole、section countを推測せず `not_evaluated` と
返す。in-memory meshについては、同じcontract gateをunit testで検証している。

## 実測値

| asset | bytes | mesh/node/material | vertex | index / triangle | hair semantic | quad tube |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `LumiMagical.glb` | 83,069,060 | 1 / 1 / 1 | 918,731 | 4,397,610 / 1,465,870 | なし | 証明不可 |
| `カラフルヘアガール顔.glb` | 76,085,592 | 1 / 1 / 1 | 919,739 | 4,490,208 / 1,496,736 | なし | 証明不可 |
| `桃髪ガールダンス付き.glb` | 92,980,436 | 1 / 29 / 1 | 854,274 | 4,493,754 / 1,497,918 | なし | 証明不可 |
| `照れ前髪ガール.glb` | 83,095,368 | 1 / 1 / 1 | 918,026 | 4,469,118 / 1,489,706 | なし | 証明不可 |
| `雨に濡れた少女.glb` | 79,625,052 | 1 / 1 / 1 | 930,570 | 4,470,438 / 1,490,146 | なし | 証明不可 |

全5件の唯一の primitive は `mode=4 (TRIANGLES)` で、source face arityは3である。
glTF 2.0のtriangle primitiveからquad pairを暗黙に復元する処理はprobeに入れていない。
任意の三角形pairをquadとみなすと、root loopとrailの対応を誤って受理するためである。

| contract項目 | 実髪GLBでの結果 | fail-closed理由 |
| --- | --- | --- |
| 4-sided quad比率 | 0 / 5 = 0% | `TRIANGULATED_INPUT`、`NON_QUAD_FACE` |
| root / tip reachability | 未評価 | `HAIR_COMPONENT_NOT_SEPARABLE`、`ROOT_TIP_NOT_EVALUATED` |
| cap | 未評価 | 髪componentを分離できない |
| pole | 未評価 | 髪componentを分離できない |
| section数変化 | 未評価 | 髪componentを分離できない |

## 入力contractへの判断

- Phase 0の4-rail contract自体は、in-memoryの正常open tubeと2-cap tubeで受理できる。
- triangle、pole、root/tip不明、section数変化の曖昧入力は、rail抽出前に拒否する。
- 今回のGLB corpusは、髪の形状品質を承認するGoldenではない。flatten済みtriangle mesh
  なので、4-rail MVPの実髪適用率を測る資料としては不十分である。
- `HAIR-TUBE-TOPO-1`へ進む前に、MayaまたはBlenderで髪objectを単独選択できる実アセット、
  またはroot edge loopを指定したflat bufferをfixtureとして収集する必要がある。
- DCC import後にquad source topologyをread-backできる場合だけ、root/tip、cap、pole、
  section数変化を再計測する。triangulated exportからの自動quad推測は行わない。

## テストと限界

`tests/common/test_hair_tube_probe.py` は、次をsynthetic in-memory fixtureで検証する。

- 4頂点ringが3 station続くopen tube（root/tip、station、capなし）
- 2つのquad capを持つclosed tube
- triangle faceを含む入力
- pole vertexを含む入力
- station sizeが変化する曖昧入力

synthetic testのgreenは、実髪GLBが4-sided tubeである証拠ではない。今回未検証なのは、
髪objectを分離したDCC read-back、実meshのroot loop選択、UV/skin weight、Maya/Blender
GUI smokeである。
