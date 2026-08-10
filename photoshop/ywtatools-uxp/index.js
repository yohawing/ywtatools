const { app, constants, core } = require("photoshop");
const { entrypoints, storage } = require("uxp");
const { TEXTURE_MAPS, buildExportPlan, normalizeGroupName } = require("./texture-contract");

let outputFolder = null;

/** パネルのステータス表示を更新する。 */
function setStatus(message, isError = false) {
    const status = document.getElementById("status");
    if (!status) {
        return;
    }
    status.textContent = message;
    status.classList.toggle("error", isError);
}

/** アクティブドキュメントを取得し、無い場合はエラーにする。 */
function requireActiveDocument() {
    if (app.documents.length === 0) {
        throw new Error("PSDを開いてください。");
    }
    return app.activeDocument;
}

/** ドキュメント直下のレイヤーグループだけを返す。 */
function getTopLevelGroups(photoshopDocument) {
    return photoshopDocument.layers.filter(
        (layer) => layer.kind === constants.LayerKind.GROUP,
    );
}

/** 入力欄またはPSD名から出力のベース名を得る。 */
function getRequestedBaseName(photoshopDocument) {
    const input = document.getElementById("base-name");
    return input?.value.trim() || photoshopDocument.name;
}

/** 現在のレイヤー構成から出力予定を作る。 */
function createCurrentPlan() {
    const photoshopDocument = requireActiveDocument();
    const groups = getTopLevelGroups(photoshopDocument);
    return buildExportPlan(
        getRequestedBaseName(photoshopDocument),
        groups.map((group) => ({ name: group.name })),
    );
}

/** 検出したPBRグループと出力名を表示する。 */
function refreshPreview() {
    const list = document.getElementById("export-plan");
    if (!list) {
        return;
    }
    list.replaceChildren();

    try {
        const photoshopDocument = requireActiveDocument();
        const input = document.getElementById("base-name");
        if (input && !input.value) {
            input.value = photoshopDocument.name.replace(/\.(psd|psb)$/i, "");
        }
        const plan = createCurrentPlan();
        if (plan.length === 0) {
            const item = document.createElement("li");
            item.textContent = "既知のPBRグループがありません。";
            list.appendChild(item);
        } else {
            for (const entry of plan) {
                const item = document.createElement("li");
                item.textContent = `${entry.sourceName} → ${entry.fileName}`;
                list.appendChild(item);
            }
        }
        setStatus(`Photoshop ${app.version} / ${plan.length}マップ検出`);
    } catch (error) {
        setStatus(error.message, true);
    }
}

/** 出力フォルダをユーザーに選択してもらう。 */
async function selectOutputFolder() {
    const selected = await storage.localFileSystem.getFolder();
    if (!selected) {
        return;
    }
    outputFolder = selected;
    const label = document.getElementById("output-folder");
    if (label) {
        label.textContent = selected.nativePath || selected.name;
    }
    setStatus("出力フォルダを選択しました。");
}

/** 不足している標準PBRグループをPSDへ追加する。 */
async function createPbrTemplate() {
    try {
        const photoshopDocument = requireActiveDocument();
        const existingNames = new Set(
            getTopLevelGroups(photoshopDocument).map((group) => normalizeGroupName(group.name)),
        );
        const missingMaps = TEXTURE_MAPS.filter(
            (textureMap) =>
                !textureMap.aliases.some((alias) =>
                    existingNames.has(normalizeGroupName(alias)),
                ),
        );
        if (missingMaps.length === 0) {
            setStatus("標準PBRグループはすべて存在します。");
            return;
        }

        await core.executeAsModal(
            async (executionContext) => {
                const suspension = await executionContext.hostControl.suspendHistory({
                    documentID: photoshopDocument.id,
                    name: "PBRレイヤーグループを作成",
                });
                for (const textureMap of [...missingMaps].reverse()) {
                    await photoshopDocument.createLayerGroup({ name: textureMap.groupName });
                }
                await executionContext.hostControl.resumeHistory(suspension);
            },
            { commandName: "PBRレイヤーグループを作成" },
        );
        setStatus(`${missingMaps.length}個のPBRグループを追加しました。`);
        refreshPreview();
    } catch (error) {
        setStatus(`グループ作成に失敗しました: ${error.message}`, true);
    }
}

/** 認識したPBRグループを個別PNGとして非破壊で書き出す。 */
async function exportTextureMaps() {
    try {
        const sourceDocument = requireActiveDocument();
        if (!outputFolder) {
            throw new Error("先に出力フォルダを選択してください。");
        }
        const plan = createCurrentPlan();
        if (plan.length === 0) {
            throw new Error("書き出せるPBRグループがありません。");
        }

        const overwrite = document.getElementById("overwrite")?.checked ?? false;
        const files = [];
        for (const entry of plan) {
            const file = await outputFolder.createFile(entry.fileName, { overwrite });
            files.push({ entry, file });
        }

        await core.executeAsModal(
            async (executionContext) => {
                for (let index = 0; index < files.length; index += 1) {
                    const { entry, file } = files[index];
                    let exportDocument = null;
                    let exportDocumentId = null;
                    try {
                        exportDocument = await sourceDocument.duplicate(
                            `${entry.fileName}-export`,
                            false,
                        );
                        exportDocumentId = exportDocument.id;
                        await executionContext.hostControl.registerAutoCloseDocument(
                            exportDocumentId,
                        );
                        const exportGroups = getTopLevelGroups(exportDocument);
                        exportDocument.layers.forEach((layer) => {
                            layer.visible = false;
                        });
                        const targetGroup = exportGroups[entry.sourceIndex];
                        if (!targetGroup) {
                            throw new Error(`複製先で ${entry.sourceName} を解決できません。`);
                        }
                        targetGroup.visible = true;
                        await exportDocument.saveAs.png(file, {}, true);
                    } finally {
                        if (exportDocument && !executionContext.isCancelled) {
                            await executionContext.hostControl.unregisterAutoCloseDocument(
                                exportDocumentId,
                            );
                            exportDocument.closeWithoutSaving();
                        }
                    }
                    executionContext.reportProgress({
                        value: (index + 1) / files.length,
                        commandName: entry.fileName,
                    });
                }
            },
            { commandName: "PBRテクスチャを書き出し" },
        );
        setStatus(`${files.length}枚のテクスチャを書き出しました。`);
    } catch (error) {
        setStatus(`書き出しに失敗しました: ${error.message}`, true);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("refresh").addEventListener("click", refreshPreview);
    document.getElementById("select-folder").addEventListener("click", selectOutputFolder);
    document.getElementById("create-template").addEventListener("click", createPbrTemplate);
    document.getElementById("export").addEventListener("click", exportTextureMaps);
    document.getElementById("base-name").addEventListener("input", refreshPreview);
    refreshPreview();
});

entrypoints.setup({
    panels: {
        ywtaToolsPanel: {
            show() {
                refreshPreview();
            },
        },
    },
});
