using System;
using System.Collections.Generic;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Playables;
using UnityEngine.SceneManagement;
using Object = UnityEngine.Object;

namespace YWTA.Link.Unity
{
    internal interface IPlaybackHost
    {
        PlaybackBody Snapshot();
        PlaybackBody Poll();
        void Apply(PlaybackBody playback);
    }

    internal sealed class PlayableDirectorHost : IPlaybackHost
    {
        private readonly PlayableDirector _director;
        private PlaybackBody _last;
        private bool _applying;

        internal PlayableDirectorHost(PlayableDirector director)
        {
            _director = director != null ? director : throw new ArgumentNullException(nameof(director));
            _last = Capture(LinkProtocol.NewId());
        }

        internal PlayableDirector Director => _director;

        internal PlaybackBody Poll()
        {
            if (_applying)
            {
                return null;
            }

            PlaybackBody current = Capture(LinkProtocol.NewId());
            bool stateChanged = current.state != _last.state;
            bool seekedWhilePaused = current.state == "paused" && current.position.time != _last.position.time;
            bool settingsChanged = current.playback_range.end_exclusive != _last.playback_range.end_exclusive ||
                                   current.loop_mode != _last.loop_mode;
            _last = current;
            return stateChanged || seekedWhilePaused || settingsChanged ? current : null;
        }

        internal PlaybackBody Snapshot()
        {
            return Capture(LinkProtocol.NewId());
        }

        internal void Apply(PlaybackBody playback)
        {
            ValidateRemote(playback);
            _applying = true;
            try
            {
                _director.extrapolationMode = playback.loop_mode == "loop" ? DirectorWrapMode.Loop : DirectorWrapMode.Hold;
                _director.time = playback.position.time / (double)LinkProtocol.WireTicksPerSecond;
                _director.Evaluate();
                if (playback.state == "playing")
                {
                    _director.Play();
                }
                else
                {
                    _director.Pause();
                    _director.time = playback.position.time / (double)LinkProtocol.WireTicksPerSecond;
                    _director.Evaluate();
                }

                _last = Capture(playback.change_id);
            }
            finally
            {
                _applying = false;
            }
        }

        private PlaybackBody Capture(string changeId)
        {
            if (_director.playableAsset == null)
            {
                throw new InvalidOperationException("PlayableDirector has no playable asset");
            }

            string loopMode;
            switch (_director.extrapolationMode)
            {
                case DirectorWrapMode.Loop:
                    loopMode = "loop";
                    break;
                case DirectorWrapMode.None:
                case DirectorWrapMode.Hold:
                    loopMode = "once";
                    break;
                default:
                    throw new NotSupportedException("PlayableDirector wrap mode is unsupported");
            }

            return new PlaybackBody
            {
                state = _director.state == PlayState.Playing ? "playing" : "paused",
                position = new TimeValue
                {
                    time = ToTicks(_director.time),
                    timebase = WireRate()
                },
                playback_range = new TimeValue
                {
                    start = 0,
                    end_exclusive = ToTicks(_director.duration),
                    timebase = WireRate()
                },
                speed = 1.0,
                direction = "forward",
                loop_mode = loopMode,
                change_id = changeId
            };
        }

        private void ValidateRemote(PlaybackBody playback)
        {
            if (playback == null || playback.position == null || playback.playback_range == null ||
                playback.position.timebase == null || playback.playback_range.timebase == null)
            {
                throw new InvalidOperationException("Playback payload is incomplete");
            }

            ValidateTimebase(playback.position.timebase);
            ValidateTimebase(playback.playback_range.timebase);
            if (playback.state != "playing" && playback.state != "paused")
            {
                throw new NotSupportedException("Playback state is unsupported");
            }

            if (playback.speed != 1.0 || playback.direction != "forward")
            {
                throw new NotSupportedException("Unity Timeline currently supports forward 1x synchronization only");
            }

            if (playback.loop_mode == "ping-pong")
            {
                throw new NotSupportedException("Unity PlayableDirector does not support exact ping-pong playback");
            }

            if (playback.loop_mode != "once" && playback.loop_mode != "loop")
            {
                throw new NotSupportedException("Playback loop mode is unsupported");
            }

            long localDuration = ToTicks(_director.duration);
            if (playback.playback_range.start != 0 || playback.playback_range.end_exclusive != localDuration)
            {
                throw new NotSupportedException("Remote playback duration differs from the local PlayableDirector duration");
            }

            if (playback.position.time < 0 || playback.position.time > localDuration)
            {
                throw new InvalidOperationException("Playback position is outside the local duration");
            }
        }

        private static void ValidateTimebase(RationalRate rate)
        {
            if (rate.rate_num != LinkProtocol.WireTicksPerSecond || rate.rate_den != 1)
            {
                throw new NotSupportedException("Playback timebase must be exactly 120000/1");
            }
        }

        private static RationalRate WireRate()
        {
            return new RationalRate { rate_num = LinkProtocol.WireTicksPerSecond, rate_den = 1 };
        }

        internal static long ToTicks(double seconds)
        {
            if (double.IsNaN(seconds) || double.IsInfinity(seconds) || seconds < 0)
            {
                throw new InvalidOperationException("PlayableDirector time must be finite and non-negative");
            }

            double scaled = seconds * LinkProtocol.WireTicksPerSecond;
            if (scaled > StrictJson.MaxSafeInteger)
                throw new InvalidOperationException("PlayableDirector time exceeds the wire safe-integer range");
            double rounded = Math.Round(scaled);
            double tolerance = Math.Max(1.0, Math.Abs(scaled)) * 8.0 * 2.2204460492503131e-16;
            if (Math.Abs(scaled - rounded) > tolerance)
                throw new NotSupportedException("PlayableDirector time is not representable as an exact wire tick");
            return (long)rounded;
        }

        PlaybackBody IPlaybackHost.Snapshot() => Snapshot();
        PlaybackBody IPlaybackHost.Poll() => Poll();
        void IPlaybackHost.Apply(PlaybackBody playback) => Apply(playback);
    }

    internal static class PlayableDirectorSelection
    {
        internal static PlayableDirector Resolve()
        {
            return ResolveFrom(
                Selection.activeObject,
                Resources.FindObjectsOfTypeAll<PlayableDirector>().Where(IsLoadedSceneObject));
        }

        internal static PlayableDirector ResolveForTests(Object selected, IReadOnlyList<PlayableDirector> loaded)
        {
            return ResolveFrom(selected, loaded);
        }

        private static PlayableDirector ResolveFrom(Object selected, IEnumerable<PlayableDirector> candidates)
        {
            PlayableDirector only = FromSelection(selected);
            if (only != null)
            {
                return only;
            }

            foreach (PlayableDirector director in candidates.Where(value => value != null))
            {
                if (only != null)
                {
                    throw new InvalidOperationException("Timeline Sync requires a selected PlayableDirector when multiple are loaded");
                }

                only = director;
            }
            return only ?? throw new InvalidOperationException("Timeline Sync could not find a loaded PlayableDirector");
        }

        private static PlayableDirector FromSelection(Object selected)
        {
            if (selected is PlayableDirector director)
            {
                return director;
            }

            if (selected is GameObject gameObject)
            {
                return gameObject.GetComponent<PlayableDirector>();
            }

            if (selected is Component component)
            {
                return component.GetComponent<PlayableDirector>();
            }

            return null;
        }

        private static bool IsLoadedSceneObject(PlayableDirector director)
        {
            Scene scene = director.gameObject.scene;
            return scene.IsValid() && scene.isLoaded && !EditorUtility.IsPersistent(director);
        }
    }
}
