using System;
using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;

namespace YWTA.Link.Unity
{
    internal interface ILinkTransport
    {
        string PeerId { get; }
        string Failure { get; }
        bool IsFailed { get; }
        void Connect();
        void StartReceiving();
        bool TryDequeue(out LinkFrame frame);
        void SendRoute(string type, string room, string topic = null);
        string SendSlotJoin();
        string SendAuthoritySnapshotRequest(string target, string sessionId);
        void SendJson(string json);
        LinkFrame ReceiveBootstrap();
        bool Close();
    }

    internal sealed class LinkClient : IDisposable, ILinkTransport
    {
        internal const int HeaderLimit = 64 * 1024;
        internal const int ManifestLimit = 4 * 1024;
        private const int BodyLimit = 16 * 1024 * 1024;
        private readonly ConcurrentQueue<LinkFrame> _received = new ConcurrentQueue<LinkFrame>();
        private readonly int _queueCapacity;
        private TcpClient _tcp;
        private NetworkStream _stream;
        private Thread _receiver;
        private int _queuedCount;
        private volatile bool _stopping;
        private string _failure;
        private readonly Func<Thread, TimeSpan, bool> _join;

        internal LinkClient(string peerId, int queueCapacity = 256,
            Func<Thread, TimeSpan, bool> join = null, Thread receiver = null)
        {
            if (string.IsNullOrWhiteSpace(peerId))
            {
                throw new ArgumentException("peerId must not be empty", nameof(peerId));
            }

            if (queueCapacity <= 0)
            {
                throw new ArgumentOutOfRangeException(nameof(queueCapacity));
            }

            PeerId = peerId;
            _queueCapacity = queueCapacity;
            _join = join ?? ((thread, timeout) => thread.Join(timeout));
            _receiver = receiver;
        }

        internal string PeerId { get; }
        internal string Failure => Volatile.Read(ref _failure);
        internal bool IsFailed => Failure != null;
        internal bool HasReceiver => _receiver != null;

        internal void Connect()
        {
            RuntimeEndpoint endpoint = RuntimeEndpoint.Resolve();
            try
            {
            _tcp = new TcpClient(endpoint.Address.AddressFamily);
            _tcp.NoDelay = true;
            System.Threading.Tasks.Task pending = _tcp.ConnectAsync(endpoint.Address, endpoint.Port);
            if (!pending.Wait(TimeSpan.FromSeconds(1)))
            {
                _tcp.Close();
                throw new TimeoutException("YWTA Link Broker connection timed out");
            }

            pending.GetAwaiter().GetResult();
            _stream = _tcp.GetStream();
            _stream.ReadTimeout = 1000;
            _stream.WriteTimeout = 1000;

            string challenge = endpoint.Token == null ? null : LinkProtocol.NewId();
            string helloId = LinkProtocol.NewId();
            SendJson(JsonWire.RuntimeHello(PeerId, helloId, challenge));

            if (endpoint.Token != null)
            {
                LinkFrame ack = ReadFrame(_stream);
                RuntimeAckEnvelope decoded = WireDecoder.RuntimeAck(ack);
                if (ack.Body.Length != 0 || decoded.type != "hello" || decoded.sender != LinkProtocol.BrokerPeerId ||
                    decoded.correlation_id != helloId || decoded.ywta_runtime_challenge != challenge ||
                    decoded.ywta_runtime_token != endpoint.Token)
                {
                    throw new InvalidDataException("Broker runtime acknowledgement did not match the manifest");
                }
            }
            }
            catch
            {
                endpoint.ReportFailure();
                try { _tcp?.Close(); } catch (SocketException) { }
                throw;
            }
        }

        internal void StartReceiving()
        {
            if (_receiver != null)
            {
                throw new InvalidOperationException("receiver already started");
            }

            _stream.ReadTimeout = Timeout.Infinite;
            _receiver = new Thread(ReceiveLoop)
            {
                IsBackground = true,
                Name = "YWTA Link receiver"
            };
            _receiver.Start();
        }

        internal bool TryDequeue(out LinkFrame frame)
        {
            if (_received.TryDequeue(out frame))
            {
                Interlocked.Decrement(ref _queuedCount);
                return true;
            }

            return false;
        }

        internal void SendRoute(string type, string room, string topic = null)
        {
            string messageId = LinkProtocol.NewId();
            SendJson(JsonWire.Route(PeerId, messageId, type, room, topic));
        }

        internal string SendSlotJoin()
        {
            string messageId = LinkProtocol.NewId();
            SendJson(JsonWire.SlotJoin(PeerId, messageId));
            return messageId;
        }

        internal string SendAuthoritySnapshotRequest(string target, string sessionId)
        {
            string messageId = LinkProtocol.NewId();
            SendJson(JsonWire.AuthoritySnapshotRequest(PeerId, messageId, target, sessionId));
            return messageId;
        }

        internal void SendJson(string json)
        {
            if (_stream == null)
            {
                throw new InvalidOperationException("client is not connected");
            }

            byte[] frame = EncodeFrame(json, Array.Empty<byte>());
            _stream.Write(frame, 0, frame.Length);
        }

        internal static byte[] EncodeFrame(string json, byte[] body)
        {
            byte[] header = new UTF8Encoding(false, true).GetBytes(json);
            if (header.Length > HeaderLimit)
            {
                throw new InvalidDataException("frame header exceeds configured limit");
            }

            if (body == null || body.Length > BodyLimit) throw new InvalidDataException("frame body exceeds configured limit");
            byte[] frame = new byte[20 + header.Length + body.Length];
            frame[0] = (byte)'Y'; frame[1] = (byte)'W'; frame[2] = (byte)'T'; frame[3] = (byte)'L';
            BinaryPrimitives.WriteUInt16BigEndian(frame.AsSpan(4), 1);
            BinaryPrimitives.WriteUInt32BigEndian(frame.AsSpan(8), (uint)header.Length);
            BinaryPrimitives.WriteUInt64BigEndian(frame.AsSpan(12), (ulong)body.Length);
            Buffer.BlockCopy(header, 0, frame, 20, header.Length);
            Buffer.BlockCopy(body, 0, frame, 20 + header.Length, body.Length);
            return frame;
        }

        internal LinkFrame ReceiveBootstrap()
        {
            return ReadFrame(_stream);
        }

        public void Dispose()
        {
            Close();
        }

        internal bool Close()
        {
            _stopping = true;
            try
            {
                _tcp?.Close();
            }
            catch (SocketException)
            {
                // Closeはbest effortでよい。
            }

            if (_receiver != null && _receiver.IsAlive && !_join(_receiver, TimeSpan.FromMilliseconds(100)))
            {
                Interlocked.CompareExchange(ref _failure, "receiver did not stop after socket close", null);
                return false;
            }

            _receiver = null;
            _stream = null;
            _tcp = null;
            while (_received.TryDequeue(out _))
            {
            }
            Interlocked.Exchange(ref _queuedCount, 0);
            return true;
        }

        string ILinkTransport.PeerId => PeerId;
        string ILinkTransport.Failure => Failure;
        bool ILinkTransport.IsFailed => IsFailed;
        void ILinkTransport.Connect() => Connect();
        void ILinkTransport.StartReceiving() => StartReceiving();
        bool ILinkTransport.TryDequeue(out LinkFrame frame) => TryDequeue(out frame);
        void ILinkTransport.SendRoute(string type, string room, string topic) => SendRoute(type, room, topic);
        string ILinkTransport.SendSlotJoin() => SendSlotJoin();
        string ILinkTransport.SendAuthoritySnapshotRequest(string target, string sessionId) =>
            SendAuthoritySnapshotRequest(target, sessionId);
        void ILinkTransport.SendJson(string json) => SendJson(json);
        LinkFrame ILinkTransport.ReceiveBootstrap() => ReceiveBootstrap();
        bool ILinkTransport.Close() => Close();

        private void ReceiveLoop()
        {
            try
            {
                while (!_stopping)
                {
                    LinkFrame frame = ReadFrame(_stream);
                    int count = Interlocked.Increment(ref _queuedCount);
                    if (count > _queueCapacity)
                    {
                        Interlocked.Decrement(ref _queuedCount);
                        Fail("receive queue overflow");
                        return;
                    }

                    _received.Enqueue(frame);
                }
            }
            catch (Exception exception) when (_stopping &&
                                               (exception is IOException || exception is SocketException ||
                                                exception is ObjectDisposedException))
            {
                // 明示終了でblocking readが解除された。
            }
            catch (Exception exception)
            {
                Fail(exception.GetType().Name + ": " + BoundedMessage(exception.Message));
            }
        }

        private void Fail(string message)
        {
            Interlocked.CompareExchange(ref _failure, message, null);
            _stopping = true;
            try
            {
                _tcp?.Close();
            }
            catch (SocketException)
            {
                // 既に切断済み。
            }
        }

        private static LinkFrame ReadFrame(Stream source)
        {
            byte[] fixedHeader = ReadExact(source, 20);
            if (fixedHeader[0] != 'Y' || fixedHeader[1] != 'W' || fixedHeader[2] != 'T' || fixedHeader[3] != 'L' ||
                BinaryPrimitives.ReadUInt16BigEndian(fixedHeader.AsSpan(4)) != 1 ||
                BinaryPrimitives.ReadUInt16BigEndian(fixedHeader.AsSpan(6)) != 0)
            {
                throw new InvalidDataException("invalid YWTA Link frame header");
            }

            uint headerLength = BinaryPrimitives.ReadUInt32BigEndian(fixedHeader.AsSpan(8));
            ulong bodyLength = BinaryPrimitives.ReadUInt64BigEndian(fixedHeader.AsSpan(12));
            if (headerLength > HeaderLimit || bodyLength > BodyLimit)
            {
                throw new InvalidDataException("frame length exceeds configured limit");
            }

            string json = new UTF8Encoding(false, true).GetString(ReadExact(source, (int)headerLength));
            byte[] body = ReadExact(source, (int)bodyLength);
            LinkFrame frame = new LinkFrame(json, body);
            if (frame.Header == null || frame.Header.protocol_version != 1 || string.IsNullOrEmpty(frame.Header.message_id) ||
                string.IsNullOrEmpty(frame.Header.type) || string.IsNullOrEmpty(frame.Header.sender))
            {
                throw new InvalidDataException("frame envelope is incomplete");
            }

            return frame;
        }

        private static byte[] ReadExact(Stream source, int length)
        {
            byte[] result = new byte[length];
            int offset = 0;
            while (offset < length)
            {
                int read = source.Read(result, offset, length - offset);
                if (read == 0)
                {
                    throw new EndOfStreamException("truncated YWTA Link frame");
                }

                offset += read;
            }

            return result;
        }

        private static string BoundedMessage(string message)
        {
            return string.IsNullOrEmpty(message) || message.Length <= 256
                ? message ?? string.Empty
                : message.Substring(0, 256);
        }

    }

    internal sealed class RuntimeManifest
    {
        public int protocol_version;
        public string endpoint;
        public int pid;
        public string token;
    }

    internal readonly struct RuntimeEndpoint
    {
        internal static string InstallRootOverride;
        internal static int BrokerIdleSeconds = 30;
        private RuntimeEndpoint(IPAddress address, int port, string token, string manifestPath = null,
            byte[] manifestBytes = null, DateTime manifestTime = default, int manifestPid = 0,
            bool failureRetireAllowed = false)
        {
            Address = address;
            Port = port;
            Token = token;
            _manifestPath = manifestPath;
            _manifestBytes = manifestBytes;
            _manifestTime = manifestTime;
            _manifestPid = manifestPid;
            _failureRetireAllowed = failureRetireAllowed;
        }

        internal IPAddress Address { get; }
        internal int Port { get; }
        internal string Token { get; }
        private readonly string _manifestPath;
        private readonly byte[] _manifestBytes;
        private readonly DateTime _manifestTime;
        private readonly int _manifestPid;
        private readonly bool _failureRetireAllowed;

        internal static RuntimeEndpoint Resolve()
        {
            string overrideEndpoint = Environment.GetEnvironmentVariable("YWTA_LINK_ENDPOINT");
            if (!string.IsNullOrEmpty(overrideEndpoint))
            {
                return Parse(overrideEndpoint, null);
            }

            string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string root = InstallRootOverride ?? Path.Combine(local, "YWTA", "Link");
            string path = Path.Combine(root, "runtime", "v1", "broker.json");
            RuntimeEndpoint resolved;
            if (TryManifest(path, out resolved))
            {
                return resolved;
            }

            Directory.CreateDirectory(Path.GetDirectoryName(path));
            StartBroker(ResolveExecutable(root), path);
            DateTime deadline = DateTime.UtcNow.AddSeconds(3);
            while (DateTime.UtcNow < deadline)
            {
                if (TryManifest(path, out resolved))
                {
                    return resolved;
                }
                Thread.Sleep(50);
            }
            throw new TimeoutException("YWTA Link Broker did not publish its runtime manifest");
        }

        internal static bool TryManifest(string path, out RuntimeEndpoint endpoint)
        {
            endpoint = default;
            FileInfo file = new FileInfo(path);
            if (!file.Exists || file.Length > LinkClient.ManifestLimit)
            {
                return false;
            }
            byte[] original;
            try
            {
                original = File.ReadAllBytes(path);
                RuntimeManifest manifest = WireDecoder.RuntimeManifest(new UTF8Encoding(false, true).GetString(original));
                ValidateToken(manifest.token);
                bool stale = ProcessIsProvenStale(manifest.pid, file.LastWriteTimeUtc, out bool identityKnown);
                if (stale)
                {
                    if (OldEnough(file.LastWriteTimeUtc)) RetireManifest(path, original, manifest.token);
                    return false;
                }
                RuntimeEndpoint parsed = Parse(manifest.endpoint, manifest.token);
                endpoint = new RuntimeEndpoint(parsed.Address, parsed.Port, parsed.Token, path, original,
                    file.LastWriteTimeUtc, manifest.pid, identityKnown);
                return true;
            }
            catch (IOException) { return false; }
            catch (FormatException)
            {
                if (OldEnough(file.LastWriteTimeUtc))
                    try { RetireManifest(path, File.ReadAllBytes(path), null); } catch (IOException) { }
                return false;
            }
        }

        private static bool ProcessIsProvenStale(int pid, DateTime manifestTime, out bool identityKnown)
        {
            try
            {
                Process process = Process.GetProcessById(pid);
                if (process.HasExited) { identityKnown = true; return true; }
                identityKnown = true;
                return process.StartTime.ToUniversalTime() > manifestTime.AddMilliseconds(1);
            }
            catch (ArgumentException) { identityKnown = true; return true; }
            catch (InvalidOperationException) { identityKnown = false; return false; }
            catch (System.ComponentModel.Win32Exception) { identityKnown = false; return false; }
        }

        private static bool OldEnough(DateTime time) => DateTime.UtcNow - time >= TimeSpan.FromSeconds(2);

        internal static void ValidateToken(string token)
        {
            if (token.Length > 256) throw new FormatException("runtime token is too long");
            foreach (char value in token)
                if (!(value >= 'A' && value <= 'Z') && !(value >= 'a' && value <= 'z') &&
                    !(value >= '0' && value <= '9') && value != '_' && value != '-')
                    throw new FormatException("runtime token contains an invalid character");
        }

        private static void RetireManifest(string path, byte[] expected, string expectedToken)
        {
            string stale = path + ".stale-" + LinkProtocol.NewId();
            try
            {
                File.Move(path, stale);
                byte[] moved = File.ReadAllBytes(stale);
                if (!ByteEqual(expected, moved))
                {
                    if (!File.Exists(path)) File.Move(stale, path);
                    return;
                }
                if (expectedToken != null &&
                    WireDecoder.RuntimeManifest(new UTF8Encoding(false, true).GetString(moved)).token != expectedToken)
                {
                    if (!File.Exists(path)) File.Move(stale, path);
                    return;
                }
                File.Delete(stale);
            }
            catch (FileNotFoundException) { }
        }

        internal void ReportFailure()
        {
            if (!_failureRetireAllowed || _manifestPath == null || _manifestBytes == null || !OldEnough(_manifestTime)) return;
            if (!ProcessIsProvenStale(_manifestPid, _manifestTime, out _)) return;
            try { RetireManifest(_manifestPath, _manifestBytes, Token); } catch (IOException) { }
        }

        private static bool ByteEqual(byte[] left, byte[] right)
        {
            if (left.Length != right.Length) return false;
            for (int index = 0; index < left.Length; index++)
                if (left[index] != right[index]) return false;
            return true;
        }

        private static string ResolveExecutable(string root)
        {
            string explicitPath = Environment.GetEnvironmentVariable("YWTA_LINK_EXE");
            if (!string.IsNullOrWhiteSpace(explicitPath))
            {
                string full = Path.GetFullPath(explicitPath);
                if (!File.Exists(full)) throw new FileNotFoundException("YWTA_LINK_EXE does not exist", full);
                return full;
            }
            string currentPath = Path.Combine(root, "current.json");
            FileInfo current = new FileInfo(currentPath);
            if (!current.Exists || current.Length > LinkClient.HeaderLimit)
                throw new InvalidDataException("YWTA Link current.json is missing or too large");
            var decoded = WireDecoder.CurrentInstall(File.ReadAllText(currentPath, Encoding.UTF8));
            string relative = StrictJson.String(decoded, "executable");
            if (Path.IsPathRooted(relative)) throw new InvalidDataException("current.json executable must be relative");
            string canonicalRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            string executable = Path.GetFullPath(Path.Combine(canonicalRoot, relative));
            if (!executable.StartsWith(canonicalRoot, StringComparison.OrdinalIgnoreCase) || !File.Exists(executable))
                throw new InvalidDataException("current.json executable is outside the install root or missing");
            return executable;
        }

        private static void StartBroker(string executable, string runtimePath)
        {
            string quotedRuntime = "\"" + runtimePath.Replace("\"", "\\\"") + "\"";
            Process process = Process.Start(new ProcessStartInfo(executable,
                "serve --bind 127.0.0.1:0 --idle-timeout " + BrokerIdleSeconds + " --runtime-file " + quotedRuntime)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            });
            if (process == null) throw new InvalidOperationException("YWTA Link Broker process did not start");
        }

        internal static RuntimeEndpoint Parse(string endpoint, string token)
        {
            if (string.IsNullOrEmpty(endpoint))
            {
                throw new InvalidDataException("Broker endpoint must not be empty");
            }
            int separator = endpoint.LastIndexOf(':');
            if (separator <= 0 || !int.TryParse(endpoint.Substring(separator + 1), out int port) || port < 1 || port > 65535)
            {
                throw new InvalidDataException("Broker endpoint must be numeric loopback host:port");
            }

            string host = endpoint.Substring(0, separator).Trim('[', ']');
            if (!IPAddress.TryParse(host, out IPAddress address) || !IPAddress.IsLoopback(address))
            {
                throw new InvalidDataException("Broker endpoint must use a numeric loopback address");
            }

            return new RuntimeEndpoint(address, port, token);
        }
    }
}
