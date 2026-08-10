/** PBRテクスチャのRGBAパッキングcontractとDCC非依存の合成処理。 */

const PACKED_PRESETS = Object.freeze([
    {
        id: "generic_orm",
        label: "Generic / Unreal ORM",
        suffix: "ORM",
        channels: [
            { label: "R", sourceId: "ambient_occlusion", defaultValue: 255 },
            { label: "G", sourceId: "roughness", defaultValue: 255 },
            { label: "B", sourceId: "metallic", defaultValue: 0 },
        ],
    },
    {
        id: "unity_urp_metallic_smoothness",
        label: "Unity URP Metallic Smoothness",
        suffix: "MetallicSmoothness",
        channels: [
            { label: "R", sourceId: "metallic", defaultValue: 0 },
            { label: "G", sourceId: null, defaultValue: 0 },
            { label: "B", sourceId: null, defaultValue: 0 },
            {
                label: "A",
                sourceId: "roughness",
                defaultValue: 0,
                invert: true,
            },
        ],
    },
    {
        id: "unity_hdrp_mask_map",
        label: "Unity HDRP Mask Map",
        suffix: "MaskMap",
        channels: [
            { label: "R", sourceId: "metallic", defaultValue: 0 },
            { label: "G", sourceId: "ambient_occlusion", defaultValue: 255 },
            { label: "B", sourceId: "mask", defaultValue: 0 },
            {
                label: "A",
                sourceId: "roughness",
                defaultValue: 0,
                invert: true,
            },
        ],
    },
]);

/** IDに一致するパッキングプリセットを返す。 */
function getPackedPreset(presetId) {
    return PACKED_PRESETS.find((preset) => preset.id === presetId) ?? PACKED_PRESETS[0];
}

/** 出力チャンネルの既定値で初期化したバッファを作る。 */
function createPackedBuffer(width, height, channels) {
    if (!Number.isInteger(width) || width <= 0 || !Number.isInteger(height) || height <= 0) {
        throw new Error("出力サイズは正の整数で指定してください。");
    }
    if (![3, 4].includes(channels.length)) {
        throw new Error("出力チャンネル数はRGBまたはRGBAにしてください。");
    }

    const buffer = new Uint8Array(width * height * channels.length);
    for (let pixelIndex = 0; pixelIndex < width * height; pixelIndex += 1) {
        const outputOffset = pixelIndex * channels.length;
        channels.forEach((channel, channelIndex) => {
            buffer[outputOffset + channelIndex] = channel.defaultValue;
        });
    }
    return buffer;
}

/** RGB入力をグレースケール値へ変換する。 */
function readGrayscale(data, offset, components) {
    if (components <= 2) {
        return data[offset];
    }
    return Math.round(
        data[offset] * 0.2126 +
            data[offset + 1] * 0.7152 +
            data[offset + 2] * 0.0722,
    );
}

/** 入力ピクセルのalphaを返す。 */
function readAlpha(data, offset, components) {
    if (components === 2 || components === 4) {
        return data[offset + components - 1];
    }
    return 255;
}

/** 1枚の入力マップを対応する出力チャンネルへ合成する。 */
function applySourceToPackedBuffer(
    output,
    outputWidth,
    outputHeight,
    channels,
    sourceId,
    source,
) {
    const targetChannels = channels
        .map((channel, index) => ({ ...channel, index }))
        .filter((channel) => channel.sourceId === sourceId);
    if (targetChannels.length === 0) {
        return;
    }

    const { data, width, height, components, bounds } = source;
    if (data.length !== width * height * components) {
        throw new Error(`${sourceId} のピクセル数が宣言サイズと一致しません。`);
    }

    for (let sourceY = 0; sourceY < height; sourceY += 1) {
        const targetY = bounds.top + sourceY;
        if (targetY < 0 || targetY >= outputHeight) {
            continue;
        }
        for (let sourceX = 0; sourceX < width; sourceX += 1) {
            const targetX = bounds.left + sourceX;
            if (targetX < 0 || targetX >= outputWidth) {
                continue;
            }
            const sourceOffset = (sourceY * width + sourceX) * components;
            const sourceValue = readGrayscale(data, sourceOffset, components);
            const alpha = readAlpha(data, sourceOffset, components);
            const outputOffset =
                (targetY * outputWidth + targetX) * channels.length;

            for (const targetChannel of targetChannels) {
                const sourceDefault = targetChannel.invert
                    ? 255 - targetChannel.defaultValue
                    : targetChannel.defaultValue;
                const composited = Math.round(
                    (sourceValue * alpha + sourceDefault * (255 - alpha)) / 255,
                );
                output[outputOffset + targetChannel.index] = targetChannel.invert
                    ? 255 - composited
                    : composited;
            }
        }
    }
}

module.exports = {
    PACKED_PRESETS,
    applySourceToPackedBuffer,
    createPackedBuffer,
    getPackedPreset,
};

