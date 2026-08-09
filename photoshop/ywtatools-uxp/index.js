const { app } = require("photoshop");
const { entrypoints } = require("uxp");

/** Photoshop との接続状態をパネルへ表示する。 */
function show_connection_status() {
    const status = document.getElementById("status");
    if (!status) {
        return;
    }
    const document_name = app.activeDocument?.name ?? "ドキュメント未選択";
    status.textContent = `Photoshop ${app.version} / ${document_name}`;
}

document.addEventListener("DOMContentLoaded", () => {
    document
        .getElementById("check-connection")
        .addEventListener("click", show_connection_status);
});

entrypoints.setup({
    panels: {
        ywtaToolsPanel: {
            show() {
                show_connection_status();
            },
        },
    },
});
