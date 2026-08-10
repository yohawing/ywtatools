const test = require("node:test");
const assert = require("node:assert/strict");

const {
    OUTPUT_FOLDER_TOKEN_KEY,
    restoreOutputFolder,
    saveOutputFolder,
} = require("../../photoshop/ywtatools-uxp/output-folder-store");

function createKeyValueStore(initial = {}) {
    const values = new Map(Object.entries(initial));
    return {
        getItem: (key) => values.get(key) ?? null,
        setItem: (key, value) => values.set(key, value),
        removeItem: (key) => values.delete(key),
    };
}

test("選択したフォルダの永続トークンを保存する", async () => {
    const folder = { isFolder: true, name: "Textures" };
    const keyValueStore = createKeyValueStore();
    const fileSystem = {
        createPersistentToken: async (entry) => {
            assert.equal(entry, folder);
            return "persistent-folder-token";
        },
    };

    assert.equal(await saveOutputFolder(fileSystem, keyValueStore, folder), folder);
    assert.equal(
        keyValueStore.getItem(OUTPUT_FOLDER_TOKEN_KEY),
        "persistent-folder-token",
    );
});

test("保存済みトークンからフォルダを復元する", async () => {
    const folder = { isFolder: true, name: "Textures" };
    const keyValueStore = createKeyValueStore({
        [OUTPUT_FOLDER_TOKEN_KEY]: "persistent-folder-token",
    });
    const fileSystem = {
        getEntryForPersistentToken: async (token) => {
            assert.equal(token, "persistent-folder-token");
            return folder;
        },
    };

    assert.equal(await restoreOutputFolder(fileSystem, keyValueStore), folder);
});

test("無効な永続トークンを破棄して未選択へ戻す", async () => {
    const keyValueStore = createKeyValueStore({
        [OUTPUT_FOLDER_TOKEN_KEY]: "stale-token",
    });
    const fileSystem = {
        getEntryForPersistentToken: async () => {
            throw new ReferenceError("token is not defined");
        },
    };

    assert.equal(await restoreOutputFolder(fileSystem, keyValueStore), null);
    assert.equal(keyValueStore.getItem(OUTPUT_FOLDER_TOKEN_KEY), null);
});

test("フォルダ以外は保存しない", async () => {
    const keyValueStore = createKeyValueStore();
    const fileSystem = { createPersistentToken: async () => "unused" };

    await assert.rejects(
        saveOutputFolder(fileSystem, keyValueStore, { isFolder: false }),
        /フォルダ/,
    );
});
