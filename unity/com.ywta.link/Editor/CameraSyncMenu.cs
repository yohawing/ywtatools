using System;
using UnityEditor;
using UnityEngine;

namespace YWTA.Link.Unity
{
    [InitializeOnLoad]
    internal static class CameraSyncMenu
    {
        internal const string MenuPath = "Tools/YWTA/Camera Sync";
        private static CameraSyncSession _session;
        static CameraSyncMenu() { AssemblyReloadEvents.beforeAssemblyReload += StopSynchronously; EditorApplication.playModeStateChanged += OnPlayMode; EditorApplication.quitting += StopSynchronously; }
        [MenuItem(MenuPath, priority = 2001)]
        private static void Toggle()
        {
            if (_session != null) { Stop(); return; }
            try { Camera camera = UnityCameraSelection.Resolve(); _session = CameraSyncSession.Start(new UnityCameraHost(camera)); EditorApplication.update += Pump; Menu.SetChecked(MenuPath, true); Debug.Log("[YWTA Link] Camera Sync enabled: " + camera.name); }
            catch (Exception exception) { Stop(); Debug.LogError("[YWTA Link] Camera Sync could not start: " + exception.Message); }
        }
        [MenuItem(MenuPath, true)] private static bool ValidateToggle() { Menu.SetChecked(MenuPath, _session != null); return !EditorApplication.isPlayingOrWillChangePlaymode; }
        private static void Pump() { if (_session == null) return; _session.Pump(); if (_session.IsFailed) { string failure = _session.Failure ?? "Broker connection failed"; Stop(); Debug.LogError("[YWTA Link] Camera Sync stopped: " + failure); } }
        private static void OnPlayMode(PlayModeStateChange state) { if (state == PlayModeStateChange.ExitingEditMode || state == PlayModeStateChange.EnteredPlayMode) Stop(); }
        private static void Stop() { EditorApplication.update -= Pump; EditorApplication.update -= RetryStop; _session?.Dispose(); if (_session == null || _session.IsClosed) { _session = null; Menu.SetChecked(MenuPath, false); } else EditorApplication.update += RetryStop; }
        private static void StopSynchronously() { DateTime deadline = DateTime.UtcNow.AddSeconds(1); do { Stop(); } while (_session != null && DateTime.UtcNow < deadline); EditorApplication.update -= RetryStop; if (_session != null) Debug.LogError("[YWTA Link] Camera receiver cleanup did not finish before Editor shutdown"); }
        private static void RetryStop() { Stop(); }
    }
}
