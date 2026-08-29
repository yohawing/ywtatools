using System;
using System.Diagnostics;
using System.IO;
using NUnit.Framework;

namespace YWTA.Link.Unity.Tests
{
    internal sealed class RuntimeManifestTests
    {
        private string _root;

        [SetUp]
        public void SetUp()
        {
            _root = Path.Combine(Path.GetTempPath(), "ywta-manifest-test-" + Guid.NewGuid());
            Directory.CreateDirectory(_root);
        }

        [TearDown]
        public void TearDown()
        {
            if (Directory.Exists(_root)) Directory.Delete(_root, true);
        }

        [Test]
        public void FreshMalformedAndDeadManifestsAreNotRetired()
        {
            string malformed = Path.Combine(_root, "malformed.json");
            File.WriteAllText(malformed, "{}");
            Assert.That(RuntimeEndpoint.TryManifest(malformed, out _), Is.False);
            Assert.That(File.Exists(malformed), Is.True);

            string dead = Path.Combine(_root, "dead.json");
            Write(dead, int.MaxValue, "dead-token");
            Assert.That(RuntimeEndpoint.TryManifest(dead, out _), Is.False);
            Assert.That(File.Exists(dead), Is.True);
        }

        [Test]
        public void OversizedManifestIsRejectedWithoutMutation()
        {
            string path = Path.Combine(_root, "oversized.json");
            File.WriteAllText(path, new string('x', LinkClient.ManifestLimit + 1));
            Assert.That(RuntimeEndpoint.TryManifest(path, out _), Is.False);
            Assert.That(new FileInfo(path).Length, Is.EqualTo(LinkClient.ManifestLimit + 1));
        }

        [Test]
        public void PidReuseProofRetiresOnlyAnOldSameByteManifest()
        {
            string path = Path.Combine(_root, "reused.json");
            Process current = Process.GetCurrentProcess();
            Write(path, current.Id, "old-token");
            File.SetLastWriteTimeUtc(path, current.StartTime.ToUniversalTime().AddSeconds(-10));

            Assert.That(RuntimeEndpoint.TryManifest(path, out _), Is.False);
            Assert.That(File.Exists(path), Is.False);
        }

        [Test]
        public void FailureFeedbackDoesNotRetireConcurrentReplacement()
        {
            string path = Path.Combine(_root, "broker.json");
            Write(path, Process.GetCurrentProcess().Id, "original-token");
            File.SetLastWriteTimeUtc(path, DateTime.UtcNow.AddSeconds(-3));
            Assert.That(RuntimeEndpoint.TryManifest(path, out RuntimeEndpoint endpoint), Is.True);

            Write(path, Process.GetCurrentProcess().Id, "replacement-token");
            File.SetLastWriteTimeUtc(path, DateTime.UtcNow.AddSeconds(-3));
            endpoint.ReportFailure();

            Assert.That(File.Exists(path), Is.True);
            StringAssert.Contains("replacement-token", File.ReadAllText(path));
        }

        [Test]
        public void FailureFeedbackKeepsTheSameOldTokenAndBytesWhileOwnerIsAlive()
        {
            string path = Path.Combine(_root, "broker.json");
            Write(path, Process.GetCurrentProcess().Id, "same-token");
            File.SetLastWriteTimeUtc(path, DateTime.UtcNow.AddSeconds(-3));
            Assert.That(RuntimeEndpoint.TryManifest(path, out RuntimeEndpoint endpoint), Is.True);

            endpoint.ReportFailure();

            Assert.That(File.Exists(path), Is.True);
        }

        private static void Write(string path, int pid, string token)
        {
            File.WriteAllText(path, "{\"protocol_version\":1,\"endpoint\":\"127.0.0.1:49152\"," +
                "\"pid\":" + pid + ",\"token\":\"" + token + "\"}");
        }
    }
}
