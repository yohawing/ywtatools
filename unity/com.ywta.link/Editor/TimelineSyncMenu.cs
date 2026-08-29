using System;
using UnityEditor;
using UnityEngine;

namespace YWTA.Link.Unity
{
    [InitializeOnLoad]
    internal static class TimelineSyncMenu
    {
        internal const string MenuPath = "Tools/YWTA/Timeline Sync";
        private static TimelineSyncSession _session;

        static TimelineSyncMenu()
        {
            AssemblyReloadEvents.beforeAssemblyReload += StopSynchronously;
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
            EditorApplication.quitting += StopSynchronously;
        }

        [MenuItem(MenuPath, priority = 2000)]
        private static void Toggle()
        {
            if (_session != null)
            {
                Stop();
                return;
            }

            try
            {
                PlayableDirectorHost host = new PlayableDirectorHost(PlayableDirectorSelection.Resolve());
                _session = TimelineSyncSession.Start(host);
                EditorApplication.update += Pump;
                Menu.SetChecked(MenuPath, true);
                Debug.Log("[YWTA Link] Timeline Sync enabled: " + host.Director.name);
            }
            catch (Exception exception)
            {
                Stop();
                Debug.LogError("[YWTA Link] Timeline Sync could not start: " + exception.Message);
            }
        }

        [MenuItem(MenuPath, true)]
        private static bool ValidateToggle()
        {
            Menu.SetChecked(MenuPath, _session != null);
            return !EditorApplication.isPlayingOrWillChangePlaymode;
        }

        private static void Pump()
        {
            if (_session == null)
            {
                return;
            }

            _session.Pump();
            if (_session.IsFailed)
            {
                string failure = _session.Failure ?? "Broker connection failed";
                Stop();
                Debug.LogError("[YWTA Link] Timeline Sync stopped: " + failure);
            }
        }

        private static void OnPlayModeChanged(PlayModeStateChange state)
        {
            if (state == PlayModeStateChange.ExitingEditMode || state == PlayModeStateChange.EnteredPlayMode)
            {
                Stop();
            }
        }

        private static void Stop()
        {
            EditorApplication.update -= Pump;
            EditorApplication.update -= RetryStop;
            _session?.Dispose();
            if (_session == null || _session.IsClosed)
            {
                _session = null;
                Menu.SetChecked(MenuPath, false);
            }
            else
            {
                EditorApplication.update += RetryStop;
            }
        }

        private static void StopSynchronously()
        {
            DateTime deadline = DateTime.UtcNow.AddSeconds(1);
            do
            {
                Stop();
            }
            while (_session != null && DateTime.UtcNow < deadline);
            EditorApplication.update -= RetryStop;
            if (_session != null)
                Debug.LogError("[YWTA Link] receiver cleanup did not finish before Editor shutdown");
        }

        private static void RetryStop()
        {
            Stop();
        }
    }
}
