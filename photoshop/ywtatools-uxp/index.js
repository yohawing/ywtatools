const { app, constants, core, imaging } = require("photoshop");
const { entrypoints, storage } = require("uxp");
const {
    PACKED_PRESETS,
    applySourceToPackedBuffer,
    createPackedBuffer,
    getPackedPreset,
} = require("./channel-packer");
const {
    TEXTURE_TEMPLATES,
    buildExportPlan,
    getTextureTemplate,
    normalizeGroupName,
    sanitizeBaseName,
} = require("./texture-contract");

let outputFolder = null;
const PACK_TILE_HEIGHT = 512;

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

/** UIで選択されているテクスチャテンプレートを返す。 */
function getSelectedTextureTemplate() {
    const selectedIndex =
        document.getElementById("texture-template")?.selectedIndex ?? 0;
    return getTextureTemplate(TEXTURE_TEMPLATES[selectedIndex]?.id);
}

/** 現在のレイヤー構成から個別マップの出力予定を作る。 */
function createCurrentPlan() {
    const photoshopDocument = requireActiveDocument();
    const groups = getTopLevelGroups(photoshopDocument);
    return buildExportPlan(
        getRequestedBaseName(photoshopDocument),
        groups.map((group) => ({ name: group.name })),
        getSelectedTextureTemplate().maps,
    );
}

/** UIで選択されているパッキングプリセットを返す。 */
function getSelectedPackedPreset() {
    const selectedIndex = document.getElementById("packed-preset")?.selectedIndex ?? 0;
    return getPackedPreset(PACKED_PRESETS[selectedIndex]?.id);
}

/** 個別マップの検出結果からパック出力予定を作る。 */
function createPackedPlan(individualPlan) {
    if (!getSelectedTextureTemplate().supportsPacking) {
        return null;
    }
    if (!(document.getElementById("export-packed")?.checked ?? true)) {
        return null;
    }
    const preset = getSelectedPackedPreset();
    const sourceIds = new Set(preset.channels.map((channel) => channel.sourceId).filter(Boolean));
    const sources = individualPlan.filter((entry) => sourceIds.has(entry.id));
    if (sources.length === 0) {
        return null;
    }
    const baseName = sanitizeBaseName(getRequestedBaseName(requireActiveDocument()));
    return {
        preset,
        sources,
        fileName: `${baseName}_${preset.suffix}.png`,
    };
}

/** 検出したテクスチャグループと出力名を表示する。 */
function refreshPreview() {
    const list = document.getElementById("export-plan");
    if (!list) {
        return;
    }
    list.replaceChildren();

    try {
        const template = getSelectedTextureTemplate();
        const packedControls = document.getElementById("packed-controls");
        if (packedControls) {
            packedControls.hidden = !template.supportsPacking;
        }
        const photoshopDocument = requireActiveDocument();
        const input = document.getElementById("base-name");
        if (input && !input.value) {
            input.value = photoshopDocument.name.replace(/\.(psd|psb)$/i, "");
        }
        const individualPlan = createCurrentPlan();
        const exportIndividual =
            document.getElementById("export-individual")?.checked ?? true;
        if (exportIndividual) {
            for (const entry of individualPlan) {
                const item = document.createElement("li");
                item.textContent = `${entry.sourceName} → ${entry.fileName}`;
                list.appendChild(item);
            }
        }

        const packedPlan = createPackedPlan(individualPlan);
        if (packedPlan) {
            const item = document.createElement("li");
            const sourceNames = packedPlan.sources.map((source) => source.sourceName).join(" + ");
            item.textContent = `[Pack] ${sourceNames} → ${packedPlan.fileName}`;
            list.appendChild(item);
        }

        if (list.children.length === 0) {
            const item = document.createElement("li");
            item.textContent = "書き出し対象がありません。";
            list.appendChild(item);
        }
        setStatus(
            `Photoshop ${app.version} / ${template.label} ${individualPlan.length}マップ検出`,
        );
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

/** 選択したテンプレートで不足している標準グループをPSDへ追加する。 */
async function createTextureTemplate() {
    try {
        const photoshopDocument = requireActiveDocument();
        const template = getSelectedTextureTemplate();
        const existingNames = new Set(
            getTopLevelGroups(photoshopDocument).map((group) =>
                normalizeGroupName(group.name),
            ),
        );
        const missingMaps = template.maps.filter(
            (textureMap) =>
                !textureMap.aliases.some((alias) =>
                    existingNames.has(normalizeGroupName(alias)),
                ),
        );
        if (missingMaps.length === 0) {
            setStatus(`標準${template.label}グループはすべて存在します。`);
            return;
        }

        await core.executeAsModal(
            async (executionContext) => {
                const suspension = await executionContext.hostControl.suspendHistory({
                    documentID: photoshopDocument.id,
                    name: `${template.label}レイヤーグループを作成`,
                });
                for (const textureMap of [...missingMaps].reverse()) {
                    await photoshopDocument.createLayerGroup({ name: textureMap.groupName });
                }
                await executionContext.hostControl.resumeHistory(suspension);
            },
            { commandName: `${template.label}レイヤーグループを作成` },
        );
        setStatus(`${missingMaps.length}個の${template.label}グループを追加しました。`);
        refreshPreview();
    } catch (error) {
        setStatus(`グループ作成に失敗しました: ${error.message}`, true);
    }
}

/** 自動破棄登録した一時ドキュメントを通常完了時に閉じる。 */
async function closeTemporaryDocument(executionContext, temporaryDocument) {
    if (!temporaryDocument || executionContext.isCancelled) {
        return;
    }
    await executionContext.hostControl.unregisterAutoCloseDocument(temporaryDocument.id);
    temporaryDocument.closeWithoutSaving();
}

/** 認識したグループを個別PNGとして書き出す。 */
async function exportIndividualMaps(
    sourceDocument,
    files,
    executionContext,
    progressOffset,
    progressTotal,
) {
    for (let index = 0; index < files.length; index += 1) {
        const { entry, file } = files[index];
        let exportDocument = null;
        try {
            exportDocument = await sourceDocument.duplicate(`${entry.fileName}-export`, false);
            await executionContext.hostControl.registerAutoCloseDocument(exportDocument.id);
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
            await closeTemporaryDocument(executionContext, exportDocument);
        }
        executionContext.reportProgress({
            value: (progressOffset + index + 1) / progressTotal,
            commandName: entry.fileName,
        });
    }
}

/** 1グループの合成ピクセルを現在の出力タイルへ反映する。 */
async function applyGroupTileToPackedBuffer(
    sourceDocument,
    group,
    sourceId,
    tileTop,
    tileHeight,
    packedBuffer,
    preset,
) {
    const bounds = group.boundsNoEffects;
    if (bounds.right <= bounds.left || bounds.bottom <= bounds.top) {
        return;
    }
    const left = Math.max(0, Math.floor(bounds.left));
    const right = Math.min(sourceDocument.width, Math.ceil(bounds.right));
    const top = Math.max(tileTop, Math.floor(bounds.top));
    const bottom = Math.min(tileTop + tileHeight, Math.ceil(bounds.bottom));
    if (left >= right || top >= bottom) {
        return;
    }

    const pixelResult = await imaging.getPixels({
        documentID: sourceDocument.id,
        layerID: group.id,
        sourceBounds: { left, top, right, bottom },
        colorSpace: "RGB",
        componentSize: 8,
        applyAlpha: false,
    });
    try {
        const data = await pixelResult.imageData.getData({ chunky: true });
        applySourceToPackedBuffer(
            packedBuffer,
            sourceDocument.width,
            tileHeight,
            preset.channels,
            sourceId,
            {
                data,
                width: pixelResult.imageData.width,
                height: pixelResult.imageData.height,
                components: pixelResult.imageData.components,
                bounds: {
                    left: pixelResult.sourceBounds.left,
                    top: pixelResult.sourceBounds.top - tileTop,
                },
            },
        );
    } finally {
        pixelResult.imageData.dispose();
    }
}

/** 選択されたプリセットのRGBAパックテクスチャを書き出す。 */
async function exportPackedMap(sourceDocument, packedFile, executionContext) {
    const { plan, file } = packedFile;
    const sourceGroups = getTopLevelGroups(sourceDocument);

    let packedDocument = null;
    try {
        const colorProfile =
            sourceDocument.colorProfileName === "None"
                ? null
                : sourceDocument.colorProfileName;
        const documentOptions = {
            width: sourceDocument.width,
            height: sourceDocument.height,
            resolution: sourceDocument.resolution,
            mode: "RGBColorMode",
            fill: "transparent",
            name: `${plan.fileName}-export`,
        };
        if (colorProfile) {
            documentOptions.profile = colorProfile;
        }
        packedDocument = await app.createDocument(documentOptions);
        await executionContext.hostControl.registerAutoCloseDocument(packedDocument.id);

        for (
            let tileTop = 0;
            tileTop < sourceDocument.height;
            tileTop += PACK_TILE_HEIGHT
        ) {
            const tileHeight = Math.min(
                PACK_TILE_HEIGHT,
                sourceDocument.height - tileTop,
            );
            const packedBuffer = createPackedBuffer(
                sourceDocument.width,
                tileHeight,
                plan.preset.channels,
            );
            for (const source of plan.sources) {
                const sourceGroup = sourceGroups[source.sourceIndex];
                if (!sourceGroup) {
                    throw new Error(`${source.sourceName} を解決できません。`);
                }
                await applyGroupTileToPackedBuffer(
                    sourceDocument,
                    sourceGroup,
                    source.id,
                    tileTop,
                    tileHeight,
                    packedBuffer,
                    plan.preset,
                );
            }

            const imageDataOptions = {
                width: sourceDocument.width,
                height: tileHeight,
                components: plan.preset.channels.length,
                chunky: true,
                colorSpace: "RGB",
            };
            if (colorProfile) {
                imageDataOptions.colorProfile = colorProfile;
            }
            const packedImageData = await imaging.createImageDataFromBuffer(
                packedBuffer,
                imageDataOptions,
            );
            try {
                await imaging.putPixels({
                    documentID: packedDocument.id,
                    layerID: packedDocument.layers[0].id,
                    imageData: packedImageData,
                    replace: false,
                    targetBounds: { left: 0, top: tileTop },
                    commandName: plan.preset.label,
                });
            } finally {
                packedImageData.dispose();
            }
        }
        await packedDocument.saveAs.png(file, {}, true);
    } finally {
        await closeTemporaryDocument(executionContext, packedDocument);
    }
}

/** 認識したグループを個別またはパック済みPNGとして非破壊で書き出す。 */
async function exportTextureMaps() {
    try {
        const sourceDocument = requireActiveDocument();
        if (!outputFolder) {
            throw new Error("先に出力フォルダを選択してください。");
        }
        const individualPlan = createCurrentPlan();
        const exportIndividual =
            document.getElementById("export-individual")?.checked ?? true;
        const selectedIndividualPlan = exportIndividual ? individualPlan : [];
        const packedPlan = createPackedPlan(individualPlan);
        if (selectedIndividualPlan.length === 0 && !packedPlan) {
            throw new Error("書き出せるテクスチャグループがありません。");
        }

        const overwrite = document.getElementById("overwrite")?.checked ?? false;
        const individualFiles = [];
        for (const entry of selectedIndividualPlan) {
            const file = await outputFolder.createFile(entry.fileName, { overwrite });
            individualFiles.push({ entry, file });
        }
        const packedFile = packedPlan
            ? {
                  plan: packedPlan,
                  file: await outputFolder.createFile(packedPlan.fileName, { overwrite }),
              }
            : null;
        const outputCount = individualFiles.length + (packedFile ? 1 : 0);

        await core.executeAsModal(
            async (executionContext) => {
                await exportIndividualMaps(
                    sourceDocument,
                    individualFiles,
                    executionContext,
                    0,
                    outputCount,
                );
                if (packedFile) {
                    await exportPackedMap(sourceDocument, packedFile, executionContext);
                    executionContext.reportProgress({
                        value: 1,
                        commandName: packedFile.plan.fileName,
                    });
                }
            },
            { commandName: "テクスチャを書き出し" },
        );
        setStatus(`${outputCount}枚のテクスチャを書き出しました。`);
    } catch (error) {
        setStatus(`書き出しに失敗しました: ${error.message}`, true);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("refresh").addEventListener("click", refreshPreview);
    document.getElementById("select-folder").addEventListener("click", selectOutputFolder);
    document
        .getElementById("create-template")
        .addEventListener("click", createTextureTemplate);
    document.getElementById("export").addEventListener("click", exportTextureMaps);
    document.getElementById("base-name").addEventListener("input", refreshPreview);
    document.getElementById("export-individual").addEventListener("change", refreshPreview);
    document.getElementById("export-packed").addEventListener("change", refreshPreview);
    document.getElementById("packed-preset").addEventListener("change", refreshPreview);
    document.getElementById("texture-template").addEventListener("change", refreshPreview);
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
