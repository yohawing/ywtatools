const test = require("node:test");
const assert = require("node:assert/strict");

const {
    TEXTURE_MAPS,
    buildExportPlan,
    detectTextureGroups,
    normalizeGroupName,
    sanitizeBaseName,
} = require("../../photoshop/ywtatools-uxp/texture-contract");

test("標準PBRマップを一意に定義する", () => {
    assert.equal(TEXTURE_MAPS.length, 9);
    assert.equal(new Set(TEXTURE_MAPS.map((entry) => entry.id)).size, TEXTURE_MAPS.length);
    assert.equal(
        new Set(TEXTURE_MAPS.map((entry) => entry.suffix)).size,
        TEXTURE_MAPS.length,
    );
});

test("区切り文字と大文字小文字を無視してグループを認識する", () => {
    assert.equal(normalizeGroupName("Base_Color"), "basecolor");
    const matches = detectTextureGroups([
        { name: "BASE COLOR" },
        { name: "ambient-occlusion" },
        { name: "作業用" },
    ]);
    assert.deepEqual(
        matches.map((entry) => [entry.id, entry.sourceIndex]),
        [
            ["base_color", 0],
            ["ambient_occlusion", 1],
        ],
    );
});

test("PSD名と用途から安全なPNG名を作る", () => {
    const plan = buildExportPlan("Robot:Body.psd", [
        { name: "Albedo" },
        { name: "Roughness" },
        { name: "Metalness" },
    ]);
    assert.deepEqual(
        plan.map((entry) => entry.fileName),
        ["Robot_Body_BaseColor.png", "Robot_Body_Roughness.png", "Robot_Body_Metallic.png"],
    );
});

test("空または不正なベース名を安全に処理する", () => {
    assert.equal(sanitizeBaseName("<>.psd"), "__");
    assert.equal(sanitizeBaseName("   "), "texture");
});

