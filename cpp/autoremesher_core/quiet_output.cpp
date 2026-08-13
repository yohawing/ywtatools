#include "quiet_output.h"

#include <geogram/NL/nl.h>
#include <geogram/basic/logger.h>

#include <cstdio>
#include <iostream>
#include <mutex>
#include <streambuf>
#include <string>
#include <thread>

namespace ywta {
namespace autoremesher {
namespace {

std::mutex& outputMutex()
{
    static std::mutex mutex;
    return mutex;
}

bool startsWith(const std::string& value, const char* prefix)
{
    return value.compare(0, std::char_traits<char>::length(prefix), prefix) == 0;
}

bool isNoisyProgressLine(const std::string& line)
{
    static const char* prefixes[] = {
        " check_that multiplicity",
        "New LS iteration",
        "Try enforce mutiplicity",
        "Extract connections",
        "Extract edges",
        "Extract mesh",
        "collapseTriangles clusters:",
        "group:",
        "group[",
        "Searching boundaries",
        "Searching loop from:",
        "Found valid loop, size:",
        "Loop add vertex:",
        "Break loop, because of next size:",
    };
    for (const char* prefix : prefixes) {
        if (startsWith(line, prefix)) {
            return true;
        }
    }
    return false;
}

class ProgressFilteringBuffer : public std::streambuf {
public:
    explicit ProgressFilteringBuffer(std::streambuf* destination)
        : m_destination(destination)
        , m_mutedThread(std::this_thread::get_id())
    {
    }

    ~ProgressFilteringBuffer() override { flushPending(); }

protected:
    int_type overflow(int_type character) override
    {
        if (traits_type::eq_int_type(character, traits_type::eof())) {
            return traits_type::not_eof(character);
        }
        const char value = traits_type::to_char_type(character);
        write(&value, 1);
        return character;
    }

    std::streamsize xsputn(const char* text, std::streamsize count) override
    {
        write(text, count);
        return count;
    }

    int sync() override
    {
        return m_destination->pubsync();
    }

private:
    void write(const char* text, std::streamsize count)
    {
        if (std::this_thread::get_id() != m_mutedThread) {
            m_destination->sputn(text, count);
            return;
        }
        for (std::streamsize index = 0; index < count; ++index) {
            m_pending.push_back(text[index]);
            if (text[index] == '\n') {
                flushPending();
            }
        }
    }

    void flushPending()
    {
        if (!m_pending.empty() && !isNoisyProgressLine(m_pending)) {
            m_destination->sputn(m_pending.data(), static_cast<std::streamsize>(m_pending.size()));
        }
        m_pending.clear();
    }

    std::streambuf* m_destination;
    std::thread::id m_mutedThread;
    std::string m_pending;
};

int quietPrintf(const char*, ...)
{
    return 0;
}

} // namespace

class ScopedQuietOutput::Impl {
public:
    Impl()
        : m_lock(outputMutex())
        , m_logger(GEO::Logger::instance())
        , m_loggerWasQuiet(m_logger->is_quiet())
        , m_cerrBuffer(std::cerr.rdbuf())
        , m_oldCerr(std::cerr.rdbuf(&m_cerrBuffer))
    {
        m_logger->set_quiet(true);
        nlPrintfFuncs(&quietPrintf, &std::fprintf);
    }

    ~Impl()
    {
        std::cerr.rdbuf(m_oldCerr);
        nlPrintfFuncs(&std::printf, &std::fprintf);
        m_logger->set_quiet(m_loggerWasQuiet);
    }

private:
    std::unique_lock<std::mutex> m_lock;
    GEO::Logger* m_logger;
    bool m_loggerWasQuiet;
    ProgressFilteringBuffer m_cerrBuffer;
    std::streambuf* m_oldCerr;
};

ScopedQuietOutput::ScopedQuietOutput()
    : m_impl(new Impl())
{
}

ScopedQuietOutput::~ScopedQuietOutput() = default;

} // namespace autoremesher
} // namespace ywta
