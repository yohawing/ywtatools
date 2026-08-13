#pragma once

#include <memory>

namespace ywta {
namespace autoremesher {

/** AutoRemesher実行中の既知の進捗ログだけを抑制するRAII guard。 */
class ScopedQuietOutput {
public:
    ScopedQuietOutput();
    ~ScopedQuietOutput();

    ScopedQuietOutput(const ScopedQuietOutput&) = delete;
    ScopedQuietOutput& operator=(const ScopedQuietOutput&) = delete;

private:
    class Impl;
    std::unique_ptr<Impl> m_impl;
};

} // namespace autoremesher
} // namespace ywta
