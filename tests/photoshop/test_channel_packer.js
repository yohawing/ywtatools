const test = require("node:test");
const assert = require("node:assert/strict");

const {
    PACKED_PRESETS,
    applySourceToPackedBuffer,
    createPackedBuffer,
    getPackedPreset,
} = require("../../photoshop/ywtatools-uxp/channel-packer");

function source(data, width, height, components, left = 0, top = 0) {
    return {
        data: Uint8Array.from(data),
        width,
        height,
        components,
        bounds: { left, top },
    };
}

test("3種類のengine向けプリセットを定義する", () => {
    assert.deepEqual(
        PACKED_PRESETS.map((preset) => preset.id),
        ["generic_orm", "unity_urp_metallic_smoothness", "unity_hdrp_mask_map"],
    );
});

test("ORMの各入力をRGBへ割り当てる", () => {
    const preset = getPackedPreset("generic_orm");
    const output = createPackedBuffer(2, 1, preset.channels);
    applySourceToPackedBuffer(
        output,
        2,
        1,
        preset.channels,
        "ambient_occlusion",
        source([10, 20], 2, 1, 1),
    );
    applySourceToPackedBuffer(
        output,
        2,
        1,
        preset.channels,
        "roughness",
        source([30, 40], 2, 1, 1),
    );
    applySourceToPackedBuffer(
        output,
        2,
        1,
        preset.channels,
        "metallic",
        source([50, 60], 2, 1, 1),
    );
    assert.deepEqual([...output], [10, 30, 50, 20, 40, 60]);
});

test("URP向けにroughnessをalphaのsmoothnessへ反転する", () => {
    const preset = getPackedPreset("unity_urp_metallic_smoothness");
    const output = createPackedBuffer(2, 1, preset.channels);
    applySourceToPackedBuffer(
        output,
        2,
        1,
        preset.channels,
        "roughness",
        source([0, 255], 2, 1, 1),
    );
    assert.deepEqual([...output], [0, 0, 0, 255, 0, 0, 0, 0]);
});

test("透明ピクセルを用途別の既定値へ合成する", () => {
    const preset = getPackedPreset("generic_orm");
    const output = createPackedBuffer(1, 1, preset.channels);
    applySourceToPackedBuffer(
        output,
        1,
        1,
        preset.channels,
        "roughness",
        source([0, 0], 1, 1, 2),
    );
    applySourceToPackedBuffer(
        output,
        1,
        1,
        preset.channels,
        "metallic",
        source([255, 0], 1, 1, 2),
    );
    assert.deepEqual([...output], [255, 255, 0]);
});

test("入力boundsを出力キャンバス上の正しい位置へ反映する", () => {
    const preset = getPackedPreset("generic_orm");
    const output = createPackedBuffer(3, 2, preset.channels);
    applySourceToPackedBuffer(
        output,
        3,
        2,
        preset.channels,
        "metallic",
        source([127], 1, 1, 1, 2, 1),
    );
    assert.equal(output[(1 * 3 + 2) * 3 + 2], 127);
    assert.equal(output[2], 0);
});

test("RGB入力は輝度として単一チャンネル化する", () => {
    const preset = getPackedPreset("generic_orm");
    const output = createPackedBuffer(1, 1, preset.channels);
    applySourceToPackedBuffer(
        output,
        1,
        1,
        preset.channels,
        "metallic",
        source([255, 0, 0], 1, 1, 3),
    );
    assert.equal(output[2], 54);
});

