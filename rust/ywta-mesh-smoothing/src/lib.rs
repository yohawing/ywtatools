//! Maya/Blenderから共有するメッシュスムージング基盤。
//!
//! 現段階では、データフローとABIを検証するための均一ラプラシアン参照実装
//! のみを提供する。体積保持スムージングはまだ実装していない。

use std::mem::{align_of, size_of};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr;

/// C ABIのバージョン。
pub const ABI_VERSION: u32 = 1;
/// 現在サポートするモード（均一ラプラシアン参照実装）。
pub const MODE_UNIFORM_LAPLACIAN: u32 = 0;

/// ABI関数が返すステータスコード。
pub const STATUS_OK: i32 = 0;
pub const STATUS_INVALID_ARGUMENT: i32 = 1;
pub const STATUS_ABI_MISMATCH: i32 = 2;
pub const STATUS_NULL_POINTER: i32 = 3;
pub const STATUS_LENGTH_OVERFLOW: i32 = 4;
pub const STATUS_OUTPUT_TOO_SMALL: i32 = 5;
pub const STATUS_EDGE_INDEX_OUT_OF_RANGE: i32 = 6;
pub const STATUS_NON_FINITE: i32 = 7;
pub const STATUS_OVERLAPPING_BUFFERS: i32 = 8;
pub const STATUS_UNSUPPORTED_MODE: i32 = 9;
pub const STATUS_PANIC: i32 = 10;

/// スムージングのオプション。
///
/// `struct_size` はこの構造体以上のバイト数を指定する。将来の拡張で末尾に
/// フィールドを追加しても、既知の先頭部分がこのサイズ以上なら受け付ける。
#[repr(C)]
#[derive(Clone, Copy)]
pub struct YwtaMeshSmoothingOptions {
    pub abi_version: u32,
    pub struct_size: u32,
    pub mode: u32,
    pub iterations: u32,
    pub strength: f64,
}

/// スムージング要求。ポインタは呼び出し中だけ参照し、DLLは保持しない。
#[repr(C)]
#[derive(Clone, Copy)]
pub struct YwtaMeshSmoothingRequest {
    pub abi_version: u32,
    pub struct_size: u32,
    pub positions: *const f64,
    pub position_count: u64,
    pub edges: *const u32,
    pub edge_count: u64,
    pub output: *mut f64,
    pub output_len: u64,
    pub options: *const YwtaMeshSmoothingOptions,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct AbiHeader {
    abi_version: u32,
    struct_size: u32,
}

const OPTIONS_SIZE: usize = size_of::<YwtaMeshSmoothingOptions>();
const REQUEST_SIZE: usize = size_of::<YwtaMeshSmoothingRequest>();

/// C ABIのスムージングエントリポイント。
///
/// 入力位置は `position_count * 3` 個、エッジは `edge_count * 2` 個の要素を
/// 持つ。出力は呼び出し側が確保し、入力と重ならない必要がある。成功時にも
/// DLLはメモリを確保・解放せず、ポインタを保持しない。例外はABIを越えず、
/// `STATUS_PANIC` に変換される。
///
/// # Safety
/// 呼び出し側は、requestとoptionsが有効な構造体ポインタであり、各配列が
/// 指定された要素数を保持すること、入力と出力が重ならないことを保証する。
#[no_mangle]
pub unsafe extern "C" fn ywta_mesh_smoothing_apply(
    request: *const YwtaMeshSmoothingRequest,
) -> i32 {
    match catch_unwind(AssertUnwindSafe(|| unsafe { apply_unchecked(request) })) {
        Ok(status) => status,
        Err(_) => STATUS_PANIC,
    }
}

unsafe fn apply_unchecked(request: *const YwtaMeshSmoothingRequest) -> i32 {
    if request.is_null() || !is_aligned(request, align_of::<AbiHeader>()) {
        return STATUS_NULL_POINTER;
    }

    // 構造体全体を読む前に、先頭ヘッダのサイズとバージョンを検証する。
    let header = ptr::read(request.cast::<AbiHeader>());
    if header.abi_version != ABI_VERSION || (header.struct_size as usize) < REQUEST_SIZE {
        return STATUS_ABI_MISMATCH;
    }
    if !is_aligned(request, align_of::<YwtaMeshSmoothingRequest>()) {
        return STATUS_INVALID_ARGUMENT;
    }
    let request_value = ptr::read(request);

    if request_value.options.is_null()
        || !is_aligned(request_value.options, align_of::<AbiHeader>())
    {
        return STATUS_NULL_POINTER;
    }
    let options_header = ptr::read(request_value.options.cast::<AbiHeader>());
    if options_header.abi_version != ABI_VERSION
        || (options_header.struct_size as usize) < OPTIONS_SIZE
    {
        return STATUS_ABI_MISMATCH;
    }
    if !is_aligned(
        request_value.options,
        align_of::<YwtaMeshSmoothingOptions>(),
    ) {
        return STATUS_INVALID_ARGUMENT;
    }
    let options = ptr::read(request_value.options);

    if options.mode != MODE_UNIFORM_LAPLACIAN {
        return STATUS_UNSUPPORTED_MODE;
    }
    if options.iterations == 0
        || !options.strength.is_finite()
        || !(0.0..=1.0).contains(&options.strength)
    {
        return if !options.strength.is_finite() {
            STATUS_NON_FINITE
        } else {
            STATUS_INVALID_ARGUMENT
        };
    }

    let position_count = match usize::try_from(request_value.position_count) {
        Ok(value) => value,
        Err(_) => return STATUS_LENGTH_OVERFLOW,
    };
    let edge_count = match usize::try_from(request_value.edge_count) {
        Ok(value) => value,
        Err(_) => return STATUS_LENGTH_OVERFLOW,
    };
    let position_len = match position_count.checked_mul(3) {
        Some(value) => value,
        None => return STATUS_LENGTH_OVERFLOW,
    };
    let edge_len = match edge_count.checked_mul(2) {
        Some(value) => value,
        None => return STATUS_LENGTH_OVERFLOW,
    };
    let output_len = match usize::try_from(request_value.output_len) {
        Ok(value) => value,
        Err(_) => return STATUS_LENGTH_OVERFLOW,
    };
    let output_capacity_bytes = match output_len.checked_mul(size_of::<f64>()) {
        Some(value) => value,
        None => return STATUS_LENGTH_OVERFLOW,
    };
    if output_len < position_len {
        return STATUS_OUTPUT_TOO_SMALL;
    }

    if position_len != 0 && request_value.positions.is_null() {
        return STATUS_NULL_POINTER;
    }
    if output_len != 0 && request_value.output.is_null() {
        return STATUS_NULL_POINTER;
    }
    if (position_len != 0 && !is_aligned(request_value.positions, align_of::<f64>()))
        || (output_len != 0 && !is_aligned(request_value.output, align_of::<f64>()))
    {
        return STATUS_INVALID_ARGUMENT;
    }
    if edge_len != 0
        && (request_value.edges.is_null() || !is_aligned(request_value.edges, align_of::<u32>()))
    {
        return STATUS_NULL_POINTER;
    }

    let positions_bytes = match position_len.checked_mul(size_of::<f64>()) {
        Some(value) => value,
        None => return STATUS_LENGTH_OVERFLOW,
    };
    let edges_bytes = match edge_len.checked_mul(size_of::<u32>()) {
        Some(value) => value,
        None => return STATUS_LENGTH_OVERFLOW,
    };
    if ranges_overlap(
        request_value.positions.cast::<u8>(),
        positions_bytes,
        request_value.output.cast::<u8>(),
        output_capacity_bytes,
    ) || ranges_overlap(
        request_value.edges.cast::<u8>(),
        edges_bytes,
        request_value.output.cast::<u8>(),
        output_capacity_bytes,
    ) {
        return STATUS_OVERLAPPING_BUFFERS;
    }

    let positions = if position_len == 0 {
        &[][..]
    } else {
        // 上記の検証でNULL、アライメント、要素数、非重複を確認済み。
        std::slice::from_raw_parts(request_value.positions, position_len)
    };
    let edges = if edge_len == 0 {
        &[][..]
    } else {
        std::slice::from_raw_parts(request_value.edges, edge_len)
    };
    if positions.iter().any(|value| !value.is_finite()) {
        return STATUS_NON_FINITE;
    }
    for &index in edges {
        if (index as usize) >= position_count {
            return STATUS_EDGE_INDEX_OUT_OF_RANGE;
        }
    }

    let smoothed = match uniform_laplacian(positions, position_count, edges, options) {
        Ok(value) => value,
        Err(status) => return status,
    };
    if position_len != 0 {
        // 出力は呼び出し側所有であり、入力と重ならない契約を検証済み。
        ptr::copy_nonoverlapping(smoothed.as_ptr(), request_value.output, position_len);
    }
    STATUS_OK
}

fn is_aligned<T>(pointer: *const T, alignment: usize) -> bool {
    (pointer as usize).is_multiple_of(alignment)
}

fn ranges_overlap(a: *const u8, a_len: usize, b: *const u8, b_len: usize) -> bool {
    if a_len == 0 || b_len == 0 {
        return false;
    }
    let a_start = a as usize;
    let b_start = b as usize;
    let Some(a_end) = a_start.checked_add(a_len) else {
        return true;
    };
    let Some(b_end) = b_start.checked_add(b_len) else {
        return true;
    };
    a_start < b_end && b_start < a_end
}

fn uniform_laplacian(
    positions: &[f64],
    position_count: usize,
    edges: &[u32],
    options: YwtaMeshSmoothingOptions,
) -> Result<Vec<f64>, i32> {
    let mut current = positions.to_vec();
    let mut sums = vec![[0.0_f64; 3]; position_count];
    let mut counts = vec![0_u32; position_count];

    for _ in 0..options.iterations {
        sums.fill([0.0; 3]);
        counts.fill(0);
        for pair in edges.chunks_exact(2) {
            let a = pair[0] as usize;
            let b = pair[1] as usize;
            for (sum, value) in sums[a].iter_mut().zip(&current[b * 3..b * 3 + 3]) {
                *sum += *value;
            }
            for (sum, value) in sums[b].iter_mut().zip(&current[a * 3..a * 3 + 3]) {
                *sum += *value;
            }
            counts[a] = counts[a].saturating_add(1);
            counts[b] = counts[b].saturating_add(1);
        }
        if sums.iter().flatten().any(|value| !value.is_finite()) {
            return Err(STATUS_NON_FINITE);
        }

        let mut next = current.clone();
        for vertex in 0..position_count {
            if counts[vertex] == 0 {
                continue;
            }
            let inverse_count = 1.0 / f64::from(counts[vertex]);
            for (axis, sum) in sums[vertex].iter().enumerate() {
                let index = vertex * 3 + axis;
                let average = *sum * inverse_count;
                let current_value = next[index];
                next[index] += options.strength * (average - current_value);
            }
        }
        if next.iter().any(|value| !value.is_finite()) {
            return Err(STATUS_NON_FINITE);
        }
        current = next;
    }
    Ok(current)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn options() -> YwtaMeshSmoothingOptions {
        YwtaMeshSmoothingOptions {
            abi_version: ABI_VERSION,
            struct_size: OPTIONS_SIZE as u32,
            mode: MODE_UNIFORM_LAPLACIAN,
            iterations: 1,
            strength: 0.5,
        }
    }

    #[test]
    fn abi_layout_matches_documented_c_layout() {
        // Maya/Blenderの現行Windowsビルドは64-bitを前提とする。
        assert_eq!(size_of::<YwtaMeshSmoothingOptions>(), 24);
        assert_eq!(align_of::<YwtaMeshSmoothingOptions>(), 8);
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingOptions, abi_version),
            0
        );
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingOptions, struct_size),
            4
        );
        assert_eq!(std::mem::offset_of!(YwtaMeshSmoothingOptions, mode), 8);
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingOptions, iterations),
            12
        );
        assert_eq!(std::mem::offset_of!(YwtaMeshSmoothingOptions, strength), 16);
        assert_eq!(size_of::<YwtaMeshSmoothingRequest>(), 64);
        assert_eq!(align_of::<YwtaMeshSmoothingRequest>(), 8);
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingRequest, abi_version),
            0
        );
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingRequest, struct_size),
            4
        );
        assert_eq!(std::mem::offset_of!(YwtaMeshSmoothingRequest, positions), 8);
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingRequest, position_count),
            16
        );
        assert_eq!(std::mem::offset_of!(YwtaMeshSmoothingRequest, edges), 24);
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingRequest, edge_count),
            32
        );
        assert_eq!(std::mem::offset_of!(YwtaMeshSmoothingRequest, output), 40);
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingRequest, output_len),
            48
        );
        assert_eq!(std::mem::offset_of!(YwtaMeshSmoothingRequest, options), 56);
    }

    fn request<'a>(
        positions: &'a [f64],
        edges: &'a [u32],
        output: &'a mut [f64],
        options: &'a YwtaMeshSmoothingOptions,
    ) -> YwtaMeshSmoothingRequest {
        YwtaMeshSmoothingRequest {
            abi_version: ABI_VERSION,
            struct_size: REQUEST_SIZE as u32,
            positions: positions.as_ptr(),
            position_count: (positions.len() / 3) as u64,
            edges: edges.as_ptr(),
            edge_count: (edges.len() / 2) as u64,
            output: output.as_mut_ptr(),
            output_len: output.len() as u64,
            options,
        }
    }

    #[test]
    fn uniform_laplacian_moves_vertices_towards_neighbour() {
        let positions = [0.0, 0.0, 0.0, 2.0, 0.0, 0.0];
        let edges = [0, 1];
        let result = uniform_laplacian(&positions, 2, &edges, options()).expect("成功");
        assert_eq!(result, [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]);
    }

    #[test]
    fn ffi_rejects_bad_abi() {
        let positions = [0.0; 3];
        let edges: [u32; 0] = [];
        let mut output = [0.0; 3];
        let opts = options();
        let mut req = request(&positions, &edges, &mut output, &opts);
        req.abi_version = ABI_VERSION + 1;
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_ABI_MISMATCH
        );
    }

    #[test]
    fn ffi_rejects_null_pointer_with_nonzero_length() {
        let edges: [u32; 0] = [];
        let mut output = [0.0; 3];
        let opts = options();
        let req = YwtaMeshSmoothingRequest {
            abi_version: ABI_VERSION,
            struct_size: REQUEST_SIZE as u32,
            positions: ptr::null(),
            position_count: 1,
            edges: edges.as_ptr(),
            edge_count: 0,
            output: output.as_mut_ptr(),
            output_len: 3,
            options: &opts,
        };
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_NULL_POINTER
        );
    }

    #[test]
    fn ffi_rejects_small_output() {
        let positions = [0.0; 3];
        let edges: [u32; 0] = [];
        let mut output = [0.0; 2];
        let opts = options();
        let req = request(&positions, &edges, &mut output, &opts);
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_OUTPUT_TOO_SMALL
        );
    }

    #[test]
    fn ffi_rejects_bad_edge_index_and_non_finite_input() {
        let positions = [0.0; 3];
        let edges = [0, 1];
        let mut output = [0.0; 3];
        let opts = options();
        let req = request(&positions, &edges, &mut output, &opts);
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_EDGE_INDEX_OUT_OF_RANGE
        );

        let positions = [f64::NAN; 3];
        let edges: [u32; 0] = [];
        let req = request(&positions, &edges, &mut output, &opts);
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_NON_FINITE
        );
    }

    #[test]
    fn ffi_rejects_overlapping_output() {
        let mut positions = [0.0; 3];
        let edges: [u32; 0] = [];
        let opts = options();
        let req = YwtaMeshSmoothingRequest {
            abi_version: ABI_VERSION,
            struct_size: REQUEST_SIZE as u32,
            positions: positions.as_ptr(),
            position_count: 1,
            edges: edges.as_ptr(),
            edge_count: 0,
            output: positions.as_mut_ptr(),
            output_len: 3,
            options: &opts,
        };
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_OVERLAPPING_BUFFERS
        );
    }

    #[test]
    fn ffi_rejects_non_finite_intermediate_sum() {
        let positions = [0.0, 0.0, 0.0, f64::MAX, 0.0, 0.0, f64::MAX, 0.0, 0.0];
        let edges = [0, 1, 0, 2];
        let mut output = [0.0; 9];
        let opts = options();
        let req = request(&positions, &edges, &mut output, &opts);
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_NON_FINITE
        );
    }
}
