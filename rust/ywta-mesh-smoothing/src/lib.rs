//! Maya/Blenderから共有するメッシュスムージング基盤。
//!
//! 均一ラプラシアンと、収縮を抑えるTaubinおよびHCを提供する。
//! Taubinは体積損失を減らす比較基準であり、厳密な体積保持ではない。
//! 頂点ウェイトと方向射影制約はDCC固有の境界・レール判定から独立している。

use std::mem::{align_of, size_of};
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::ptr;

/// C ABIのバージョン。
pub const ABI_VERSION: u32 = 1;
/// 現在サポートするモード（均一ラプラシアン参照実装）。
pub const MODE_UNIFORM_LAPLACIAN: u32 = 0;
/// 収縮を抑えるTaubinのλ/μ二段パス。
pub const MODE_TAUBIN: u32 = 1;
/// 元形状を参照してLaplacian変位を押し戻すHCスムージング。
pub const MODE_HC: u32 = 2;

pub const CONSTRAINT_FREE: u32 = 0;
pub const CONSTRAINT_FIXED: u32 = 1;
pub const CONSTRAINT_SURFACE_PLANE: u32 = 2;
pub const CONSTRAINT_RAIL_LINE: u32 = 3;
pub const CONSTRAINT_NORMAL_ONLY: u32 = 4;

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
pub const STATUS_INVALID_CONSTRAINT: i32 = 11;

/// スムージングのオプション。
///
/// UniformモードはABI v1の先頭24 bytesでも受理する。Taubinモードは
/// `taubin_mu`まで含む32 bytes、HCモードは現在の48 bytesを必要とする。
#[repr(C)]
#[derive(Clone, Copy)]
pub struct YwtaMeshSmoothingOptions {
    pub abi_version: u32,
    pub struct_size: u32,
    pub mode: u32,
    pub iterations: u32,
    pub strength: f64,
    pub taubin_mu: f64,
    pub hc_alpha: f64,
    pub hc_beta: f64,
}

/// ABI v1で公開したオプション先頭部分。
///
/// Uniformモードの既存クライアントは24 bytesのまま受理する。
#[repr(C)]
#[derive(Clone, Copy)]
struct YwtaMeshSmoothingOptionsV1 {
    abi_version: u32,
    struct_size: u32,
    mode: u32,
    iterations: u32,
    strength: f64,
}

/// Taubin追加時に公開したオプション先頭部分。
#[repr(C)]
#[derive(Clone, Copy)]
struct YwtaMeshSmoothingOptionsTaubin {
    abi_version: u32,
    struct_size: u32,
    mode: u32,
    iterations: u32,
    strength: f64,
    taubin_mu: f64,
}

#[derive(Clone, Copy)]
struct SmoothingOptions {
    mode: u32,
    iterations: u32,
    strength: f64,
    taubin_mu: f64,
    hc_alpha: f64,
    hc_beta: f64,
}

#[derive(Clone, Copy, Default)]
struct ConstraintInputs<'a> {
    weights: Option<&'a [f64]>,
    modes: Option<&'a [u32]>,
    directions: Option<&'a [f64]>,
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
    pub vertex_weights: *const f64,
    pub constraint_modes: *const u32,
    pub constraint_directions: *const f64,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct YwtaMeshSmoothingRequestV1 {
    abi_version: u32,
    struct_size: u32,
    positions: *const f64,
    position_count: u64,
    edges: *const u32,
    edge_count: u64,
    output: *mut f64,
    output_len: u64,
    options: *const YwtaMeshSmoothingOptions,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct AbiHeader {
    abi_version: u32,
    struct_size: u32,
}

const OPTIONS_SIZE: usize = size_of::<YwtaMeshSmoothingOptions>();
const OPTIONS_V1_SIZE: usize = size_of::<YwtaMeshSmoothingOptionsV1>();
const OPTIONS_TAUBIN_SIZE: usize = size_of::<YwtaMeshSmoothingOptionsTaubin>();
const REQUEST_SIZE: usize = size_of::<YwtaMeshSmoothingRequest>();
const REQUEST_V1_SIZE: usize = size_of::<YwtaMeshSmoothingRequestV1>();

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
    if header.abi_version != ABI_VERSION || (header.struct_size as usize) < REQUEST_V1_SIZE {
        return STATUS_ABI_MISMATCH;
    }
    if !is_aligned(request, align_of::<YwtaMeshSmoothingRequest>()) {
        return STATUS_INVALID_ARGUMENT;
    }
    let request_value = ptr::read(request.cast::<YwtaMeshSmoothingRequestV1>());
    let (vertex_weights_ptr, constraint_modes_ptr, constraint_directions_ptr) =
        if (header.struct_size as usize) >= REQUEST_SIZE {
            (
                ptr::addr_of!((*request).vertex_weights).read(),
                ptr::addr_of!((*request).constraint_modes).read(),
                ptr::addr_of!((*request).constraint_directions).read(),
            )
        } else {
            (ptr::null(), ptr::null(), ptr::null())
        };

    if request_value.options.is_null()
        || !is_aligned(request_value.options, align_of::<AbiHeader>())
    {
        return STATUS_NULL_POINTER;
    }
    let options_header = ptr::read(request_value.options.cast::<AbiHeader>());
    if options_header.abi_version != ABI_VERSION
        || (options_header.struct_size as usize) < OPTIONS_V1_SIZE
    {
        return STATUS_ABI_MISMATCH;
    }
    if !is_aligned(
        request_value.options,
        align_of::<YwtaMeshSmoothingOptions>(),
    ) {
        return STATUS_INVALID_ARGUMENT;
    }
    let options_v1 = ptr::read(request_value.options.cast::<YwtaMeshSmoothingOptionsV1>());

    if !matches!(
        options_v1.mode,
        MODE_UNIFORM_LAPLACIAN | MODE_TAUBIN | MODE_HC
    ) {
        return STATUS_UNSUPPORTED_MODE;
    }
    if options_v1.iterations == 0
        || !options_v1.strength.is_finite()
        || !(0.0..=1.0).contains(&options_v1.strength)
    {
        return if !options_v1.strength.is_finite() {
            STATUS_NON_FINITE
        } else {
            STATUS_INVALID_ARGUMENT
        };
    }
    let taubin_mu = if options_v1.mode == MODE_TAUBIN {
        if (options_header.struct_size as usize) < OPTIONS_TAUBIN_SIZE {
            return STATUS_ABI_MISMATCH;
        }
        let value = ptr::addr_of!((*request_value.options).taubin_mu).read();
        if !value.is_finite() {
            return STATUS_NON_FINITE;
        }
        if options_v1.strength == 0.0
            || !(-1.0..0.0).contains(&value)
            || -value <= options_v1.strength
        {
            return STATUS_INVALID_ARGUMENT;
        }
        value
    } else {
        0.0
    };
    let (hc_alpha, hc_beta) = if options_v1.mode == MODE_HC {
        if (options_header.struct_size as usize) < OPTIONS_SIZE {
            return STATUS_ABI_MISMATCH;
        }
        let alpha = ptr::addr_of!((*request_value.options).hc_alpha).read();
        let beta = ptr::addr_of!((*request_value.options).hc_beta).read();
        if !alpha.is_finite() || !beta.is_finite() {
            return STATUS_NON_FINITE;
        }
        if !(0.0..=1.0).contains(&alpha) || !(0.0..=1.0).contains(&beta) {
            return STATUS_INVALID_ARGUMENT;
        }
        (alpha, beta)
    } else {
        (0.0, 0.0)
    };
    let options = SmoothingOptions {
        mode: options_v1.mode,
        iterations: options_v1.iterations,
        strength: options_v1.strength,
        taubin_mu,
        hc_alpha,
        hc_beta,
    };

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
    if (!vertex_weights_ptr.is_null() && !is_aligned(vertex_weights_ptr, align_of::<f64>()))
        || (!constraint_modes_ptr.is_null() && !is_aligned(constraint_modes_ptr, align_of::<u32>()))
        || (!constraint_directions_ptr.is_null()
            && !is_aligned(constraint_directions_ptr, align_of::<f64>()))
    {
        return STATUS_INVALID_ARGUMENT;
    }

    let positions_bytes = match position_len.checked_mul(size_of::<f64>()) {
        Some(value) => value,
        None => return STATUS_LENGTH_OVERFLOW,
    };
    let edges_bytes = match edge_len.checked_mul(size_of::<u32>()) {
        Some(value) => value,
        None => return STATUS_LENGTH_OVERFLOW,
    };
    let weights_bytes = match position_count.checked_mul(size_of::<f64>()) {
        Some(value) => value,
        None => return STATUS_LENGTH_OVERFLOW,
    };
    let modes_bytes = match position_count.checked_mul(size_of::<u32>()) {
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
    ) || ranges_overlap(
        vertex_weights_ptr.cast::<u8>(),
        if vertex_weights_ptr.is_null() {
            0
        } else {
            weights_bytes
        },
        request_value.output.cast::<u8>(),
        output_capacity_bytes,
    ) || ranges_overlap(
        constraint_modes_ptr.cast::<u8>(),
        if constraint_modes_ptr.is_null() {
            0
        } else {
            modes_bytes
        },
        request_value.output.cast::<u8>(),
        output_capacity_bytes,
    ) || ranges_overlap(
        constraint_directions_ptr.cast::<u8>(),
        if constraint_directions_ptr.is_null() {
            0
        } else {
            positions_bytes
        },
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
    let vertex_weights = if vertex_weights_ptr.is_null() {
        None
    } else {
        Some(std::slice::from_raw_parts(
            vertex_weights_ptr,
            position_count,
        ))
    };
    let constraint_modes = if constraint_modes_ptr.is_null() {
        None
    } else {
        Some(std::slice::from_raw_parts(
            constraint_modes_ptr,
            position_count,
        ))
    };
    let constraint_directions = if constraint_directions_ptr.is_null() {
        None
    } else {
        Some(std::slice::from_raw_parts(
            constraint_directions_ptr,
            position_len,
        ))
    };
    if positions.iter().any(|value| !value.is_finite()) {
        return STATUS_NON_FINITE;
    }
    for &index in edges {
        if (index as usize) >= position_count {
            return STATUS_EDGE_INDEX_OUT_OF_RANGE;
        }
    }
    if let Some(weights) = vertex_weights {
        if weights
            .iter()
            .any(|weight| !weight.is_finite() || !(0.0..=1.0).contains(weight))
        {
            return STATUS_INVALID_CONSTRAINT;
        }
    }
    if let Some(modes) = constraint_modes {
        for (vertex, &mode) in modes.iter().enumerate() {
            if mode > CONSTRAINT_NORMAL_ONLY {
                return STATUS_INVALID_CONSTRAINT;
            }
            if matches!(
                mode,
                CONSTRAINT_SURFACE_PLANE | CONSTRAINT_RAIL_LINE | CONSTRAINT_NORMAL_ONLY
            ) {
                let Some(directions) = constraint_directions else {
                    return STATUS_NULL_POINTER;
                };
                let direction = &directions[vertex * 3..vertex * 3 + 3];
                let length_squared = direction.iter().map(|value| value * value).sum::<f64>();
                if !length_squared.is_finite() || length_squared <= f64::EPSILON {
                    return STATUS_INVALID_CONSTRAINT;
                }
            }
        }
    }
    let constraints = ConstraintInputs {
        weights: vertex_weights,
        modes: constraint_modes,
        directions: constraint_directions,
    };

    let smoothed = match smooth_positions(positions, position_count, edges, options, constraints) {
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

fn smooth_positions(
    positions: &[f64],
    position_count: usize,
    edges: &[u32],
    options: SmoothingOptions,
    constraints: ConstraintInputs<'_>,
) -> Result<Vec<f64>, i32> {
    let mut current = positions.to_vec();
    let original = positions;
    let mut sums = vec![[0.0_f64; 3]; position_count];
    let mut counts = vec![0_u32; position_count];

    for _ in 0..options.iterations {
        if options.mode == MODE_HC {
            current = hc_iteration(
                original,
                &current,
                edges,
                options,
                constraints,
                &mut sums,
                &mut counts,
            )?;
            continue;
        }
        current = laplacian_pass(
            &current,
            position_count,
            edges,
            options.strength,
            constraints,
            &mut sums,
            &mut counts,
        )?;
        if options.mode == MODE_TAUBIN {
            current = laplacian_pass(
                &current,
                position_count,
                edges,
                options.taubin_mu,
                constraints,
                &mut sums,
                &mut counts,
            )?;
        }
    }
    Ok(current)
}

fn hc_iteration(
    original: &[f64],
    current: &[f64],
    edges: &[u32],
    options: SmoothingOptions,
    constraints: ConstraintInputs<'_>,
    sums: &mut [[f64; 3]],
    counts: &mut [u32],
) -> Result<Vec<f64>, i32> {
    let position_count = current.len() / 3;
    accumulate_neighbours(current, edges, sums, counts)?;
    let mut forward = current.to_vec();
    for vertex in 0..position_count {
        if counts[vertex] == 0 {
            continue;
        }
        let start = vertex * 3;
        let inverse_count = 1.0 / f64::from(counts[vertex]);
        let raw_delta = [
            options.strength * (sums[vertex][0] * inverse_count - current[start]),
            options.strength * (sums[vertex][1] * inverse_count - current[start + 1]),
            options.strength * (sums[vertex][2] * inverse_count - current[start + 2]),
        ];
        let projected = project_displacement(vertex, raw_delta, constraints);
        for axis in 0..3 {
            forward[start + axis] = current[start + axis] + projected[axis];
        }
    }

    let mut differences = vec![0.0; current.len()];
    for (vertex, difference) in differences.chunks_exact_mut(3).enumerate() {
        let start = vertex * 3;
        for axis in 0..3 {
            let reference = options.hc_alpha * original[start + axis]
                + (1.0 - options.hc_alpha) * current[start + axis];
            difference[axis] = forward[start + axis] - reference;
        }
    }
    accumulate_neighbours(&differences, edges, sums, counts)?;

    let mut next = current.to_vec();
    for vertex in 0..position_count {
        if counts[vertex] == 0 {
            continue;
        }
        let start = vertex * 3;
        let inverse_count = 1.0 / f64::from(counts[vertex]);
        let mut raw_delta = [0.0; 3];
        for axis in 0..3 {
            let correction = options.hc_beta * differences[start + axis]
                + (1.0 - options.hc_beta) * sums[vertex][axis] * inverse_count;
            raw_delta[axis] = forward[start + axis] - correction - current[start + axis];
        }
        let projected = project_displacement(vertex, raw_delta, constraints);
        let weight = constraints.weights.map_or(1.0, |weights| weights[vertex]);
        for axis in 0..3 {
            next[start + axis] = current[start + axis] + projected[axis] * weight;
        }
    }
    if next.iter().any(|value| !value.is_finite()) {
        return Err(STATUS_NON_FINITE);
    }
    Ok(next)
}

fn accumulate_neighbours(
    values: &[f64],
    edges: &[u32],
    sums: &mut [[f64; 3]],
    counts: &mut [u32],
) -> Result<(), i32> {
    sums.fill([0.0; 3]);
    counts.fill(0);
    for pair in edges.chunks_exact(2) {
        let a = pair[0] as usize;
        let b = pair[1] as usize;
        for (sum, value) in sums[a].iter_mut().zip(&values[b * 3..b * 3 + 3]) {
            *sum += *value;
        }
        for (sum, value) in sums[b].iter_mut().zip(&values[a * 3..a * 3 + 3]) {
            *sum += *value;
        }
        counts[a] = counts[a].saturating_add(1);
        counts[b] = counts[b].saturating_add(1);
    }
    if sums.iter().flatten().any(|value| !value.is_finite()) {
        return Err(STATUS_NON_FINITE);
    }
    Ok(())
}

fn laplacian_pass(
    current: &[f64],
    position_count: usize,
    edges: &[u32],
    factor: f64,
    constraints: ConstraintInputs<'_>,
    sums: &mut [[f64; 3]],
    counts: &mut [u32],
) -> Result<Vec<f64>, i32> {
    accumulate_neighbours(current, edges, sums, counts)?;

    let mut next = current.to_vec();
    for vertex in 0..position_count {
        if counts[vertex] == 0 {
            continue;
        }
        let inverse_count = 1.0 / f64::from(counts[vertex]);
        for (axis, sum) in sums[vertex].iter().enumerate() {
            let index = vertex * 3 + axis;
            let average = *sum * inverse_count;
            let mut delta = [0.0; 3];
            delta[axis] = factor * (average - current[index]);
            next[index] += delta[axis];
        }
        let start = vertex * 3;
        let raw_delta = [
            next[start] - current[start],
            next[start + 1] - current[start + 1],
            next[start + 2] - current[start + 2],
        ];
        let projected = project_displacement(vertex, raw_delta, constraints);
        let weight = constraints.weights.map_or(1.0, |weights| weights[vertex]);
        for axis in 0..3 {
            next[start + axis] = current[start + axis] + projected[axis] * weight;
        }
    }
    if next.iter().any(|value| !value.is_finite()) {
        return Err(STATUS_NON_FINITE);
    }
    Ok(next)
}

fn project_displacement(
    vertex: usize,
    displacement: [f64; 3],
    constraints: ConstraintInputs<'_>,
) -> [f64; 3] {
    let mode = constraints
        .modes
        .map_or(CONSTRAINT_FREE, |modes| modes[vertex]);
    if mode == CONSTRAINT_FREE {
        return displacement;
    }
    if mode == CONSTRAINT_FIXED {
        return [0.0; 3];
    }

    let directions = constraints.directions.expect("方向制約はFFI境界で検証済み");
    let direction = &directions[vertex * 3..vertex * 3 + 3];
    let inverse_length = 1.0
        / direction
            .iter()
            .map(|value| value * value)
            .sum::<f64>()
            .sqrt();
    let unit = [
        direction[0] * inverse_length,
        direction[1] * inverse_length,
        direction[2] * inverse_length,
    ];
    let along = displacement[0] * unit[0] + displacement[1] * unit[1] + displacement[2] * unit[2];
    let directional = [unit[0] * along, unit[1] * along, unit[2] * along];
    if mode == CONSTRAINT_SURFACE_PLANE {
        [
            displacement[0] - directional[0],
            displacement[1] - directional[1],
            displacement[2] - directional[2],
        ]
    } else {
        directional
    }
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
            strength: 0.3,
            taubin_mu: -0.34,
            hc_alpha: 0.0,
            hc_beta: 0.5,
        }
    }

    fn internal_options(mode: u32) -> SmoothingOptions {
        SmoothingOptions {
            mode,
            iterations: 1,
            strength: 0.3,
            taubin_mu: -0.34,
            hc_alpha: 0.0,
            hc_beta: 0.5,
        }
    }

    #[test]
    fn abi_layout_matches_documented_c_layout() {
        // Maya/Blenderの現行Windowsビルドは64-bitを前提とする。
        assert_eq!(size_of::<YwtaMeshSmoothingOptionsV1>(), 24);
        assert_eq!(size_of::<YwtaMeshSmoothingOptionsTaubin>(), 32);
        assert_eq!(size_of::<YwtaMeshSmoothingOptions>(), 48);
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
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingOptions, taubin_mu),
            24
        );
        assert_eq!(std::mem::offset_of!(YwtaMeshSmoothingOptions, hc_alpha), 32);
        assert_eq!(std::mem::offset_of!(YwtaMeshSmoothingOptions, hc_beta), 40);
        assert_eq!(size_of::<YwtaMeshSmoothingRequestV1>(), 64);
        assert_eq!(size_of::<YwtaMeshSmoothingRequest>(), 88);
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
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingRequest, vertex_weights),
            64
        );
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingRequest, constraint_modes),
            72
        );
        assert_eq!(
            std::mem::offset_of!(YwtaMeshSmoothingRequest, constraint_directions),
            80
        );
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
            vertex_weights: ptr::null(),
            constraint_modes: ptr::null(),
            constraint_directions: ptr::null(),
        }
    }

    #[test]
    fn uniform_laplacian_moves_vertices_towards_neighbour() {
        let positions = [0.0, 0.0, 0.0, 2.0, 0.0, 0.0];
        let edges = [0, 1];
        let result = smooth_positions(
            &positions,
            2,
            &edges,
            internal_options(MODE_UNIFORM_LAPLACIAN),
            ConstraintInputs::default(),
        )
        .expect("成功");
        assert_eq!(result, [0.6, 0.0, 0.0, 1.4, 0.0, 0.0]);
    }

    #[test]
    fn taubin_reduces_volume_loss_and_preserves_centroid() {
        let positions = [
            1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
            -1.0,
        ];
        let edges = [
            0, 2, 0, 3, 0, 4, 0, 5, 1, 2, 1, 3, 1, 4, 1, 5, 2, 4, 2, 5, 3, 4, 3, 5,
        ];
        let triangles = [
            4, 0, 2, 4, 2, 1, 4, 1, 3, 4, 3, 0, 5, 2, 0, 5, 1, 2, 5, 3, 1, 5, 0, 3,
        ];

        let uniform = smooth_positions(
            &positions,
            6,
            &edges,
            internal_options(MODE_UNIFORM_LAPLACIAN),
            ConstraintInputs::default(),
        )
        .expect("Uniform成功");
        let taubin = smooth_positions(
            &positions,
            6,
            &edges,
            internal_options(MODE_TAUBIN),
            ConstraintInputs::default(),
        )
        .expect("Taubin成功");
        let hc = smooth_positions(
            &positions,
            6,
            &edges,
            internal_options(MODE_HC),
            ConstraintInputs::default(),
        )
        .expect("HC成功");
        let original_volume = signed_volume(&positions, &triangles).abs();
        let uniform_error = (signed_volume(&uniform, &triangles).abs() - original_volume).abs();
        let taubin_error = (signed_volume(&taubin, &triangles).abs() - original_volume).abs();
        let hc_error = (signed_volume(&hc, &triangles).abs() - original_volume).abs();

        assert!(taubin_error < uniform_error);
        assert!(hc_error < uniform_error);
        for value in &taubin {
            assert!(value.is_finite());
        }
        let centroid = centroid(&taubin);
        for component in centroid {
            assert!(component.abs() < 1.0e-12);
        }
    }

    #[test]
    fn hc_uses_neighbour_correction_instead_of_simple_blend_back() {
        let positions = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 4.0, 0.0, 0.0];
        let edges = [0, 1, 1, 2];
        let result = smooth_positions(
            &positions,
            3,
            &edges,
            internal_options(MODE_HC),
            ConstraintInputs::default(),
        )
        .expect("HC成功");

        // α=0、β=0.5。隣接頂点の差分平均を使う原論文の式による値。
        let expected = [0.0, 0.0, 0.0, 1.3, 0.0, 0.0, 3.4, 0.0, 0.0];
        for (actual, expected) in result.iter().zip(expected) {
            assert!((actual - expected).abs() < 1.0e-12);
        }
    }

    #[test]
    fn constraint_projection_and_vertex_weights_are_reusable() {
        let displacement = [1.0, 2.0, 3.0];
        let directions = [0.0, 2.0, 0.0];
        let plane_mode = [CONSTRAINT_SURFACE_PLANE];
        let rail_mode = [CONSTRAINT_RAIL_LINE];
        let normal_mode = [CONSTRAINT_NORMAL_ONLY];
        let inputs = |modes| ConstraintInputs {
            weights: None,
            modes: Some(modes),
            directions: Some(&directions),
        };
        assert_eq!(
            project_displacement(0, displacement, inputs(&plane_mode)),
            [1.0, 0.0, 3.0]
        );
        assert_eq!(
            project_displacement(0, displacement, inputs(&rail_mode)),
            [0.0, 2.0, 0.0]
        );
        assert_eq!(
            project_displacement(0, displacement, inputs(&normal_mode)),
            [0.0, 2.0, 0.0]
        );

        let positions = [0.0, 0.0, 0.0, 2.0, 2.0, 0.0];
        let edges = [0, 1];
        let weights = [0.5, 1.0];
        let modes = [CONSTRAINT_FREE, CONSTRAINT_FIXED];
        let result = smooth_positions(
            &positions,
            2,
            &edges,
            SmoothingOptions {
                strength: 0.5,
                ..internal_options(MODE_UNIFORM_LAPLACIAN)
            },
            ConstraintInputs {
                weights: Some(&weights),
                modes: Some(&modes),
                directions: None,
            },
        )
        .expect("制約付きスムージング成功");
        assert_eq!(result, [0.5, 0.5, 0.0, 2.0, 2.0, 0.0]);
    }

    fn signed_volume(positions: &[f64], triangles: &[u32]) -> f64 {
        triangles
            .chunks_exact(3)
            .map(|triangle| {
                let a = &positions[triangle[0] as usize * 3..triangle[0] as usize * 3 + 3];
                let b = &positions[triangle[1] as usize * 3..triangle[1] as usize * 3 + 3];
                let c = &positions[triangle[2] as usize * 3..triangle[2] as usize * 3 + 3];
                (a[0] * (b[1] * c[2] - b[2] * c[1])
                    + a[1] * (b[2] * c[0] - b[0] * c[2])
                    + a[2] * (b[0] * c[1] - b[1] * c[0]))
                    / 6.0
            })
            .sum()
    }

    fn centroid(positions: &[f64]) -> [f64; 3] {
        let mut result = [0.0; 3];
        for point in positions.chunks_exact(3) {
            for axis in 0..3 {
                result[axis] += point[axis];
            }
        }
        let count = (positions.len() / 3) as f64;
        result.map(|value| value / count)
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
    fn ffi_accepts_legacy_options_for_uniform_only() {
        let positions = [0.0, 0.0, 0.0, 2.0, 0.0, 0.0];
        let edges = [0, 1];
        let mut output = [0.0; 6];
        let legacy_options = YwtaMeshSmoothingOptionsV1 {
            abi_version: ABI_VERSION,
            struct_size: OPTIONS_V1_SIZE as u32,
            mode: MODE_UNIFORM_LAPLACIAN,
            iterations: 1,
            strength: 0.3,
        };
        let mut req = YwtaMeshSmoothingRequest {
            abi_version: ABI_VERSION,
            struct_size: REQUEST_SIZE as u32,
            positions: positions.as_ptr(),
            position_count: 2,
            edges: edges.as_ptr(),
            edge_count: 1,
            output: output.as_mut_ptr(),
            output_len: 6,
            options: (&legacy_options as *const YwtaMeshSmoothingOptionsV1)
                .cast::<YwtaMeshSmoothingOptions>(),
            vertex_weights: ptr::null(),
            constraint_modes: ptr::null(),
            constraint_directions: ptr::null(),
        };

        assert_eq!(unsafe { ywta_mesh_smoothing_apply(&req) }, STATUS_OK);
        assert_eq!(output, [0.6, 0.0, 0.0, 1.4, 0.0, 0.0]);

        let legacy_taubin = YwtaMeshSmoothingOptionsV1 {
            mode: MODE_TAUBIN,
            ..legacy_options
        };
        req.options = (&legacy_taubin as *const YwtaMeshSmoothingOptionsV1)
            .cast::<YwtaMeshSmoothingOptions>();
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_ABI_MISMATCH
        );

        let taubin_options = YwtaMeshSmoothingOptionsTaubin {
            abi_version: ABI_VERSION,
            struct_size: OPTIONS_TAUBIN_SIZE as u32,
            mode: MODE_TAUBIN,
            iterations: 1,
            strength: 0.3,
            taubin_mu: -0.34,
        };
        req.options = (&taubin_options as *const YwtaMeshSmoothingOptionsTaubin)
            .cast::<YwtaMeshSmoothingOptions>();
        assert_eq!(unsafe { ywta_mesh_smoothing_apply(&req) }, STATUS_OK);

        let hc_options = YwtaMeshSmoothingOptionsTaubin {
            mode: MODE_HC,
            ..taubin_options
        };
        req.options = (&hc_options as *const YwtaMeshSmoothingOptionsTaubin)
            .cast::<YwtaMeshSmoothingOptions>();
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_ABI_MISMATCH
        );
    }

    #[test]
    fn ffi_rejects_invalid_taubin_parameters() {
        let positions = [0.0; 3];
        let edges: [u32; 0] = [];
        let mut output = [0.0; 3];
        let mut opts = options();
        opts.mode = MODE_TAUBIN;
        opts.taubin_mu = -0.2;
        {
            let req = request(&positions, &edges, &mut output, &opts);
            assert_eq!(
                unsafe { ywta_mesh_smoothing_apply(&req) },
                STATUS_INVALID_ARGUMENT
            );
        }

        opts.taubin_mu = f64::NAN;
        let req = request(&positions, &edges, &mut output, &opts);
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_NON_FINITE
        );
    }

    #[test]
    fn ffi_rejects_invalid_hc_parameters() {
        let positions = [0.0; 3];
        let edges: [u32; 0] = [];
        let mut output = [0.0; 3];
        let mut opts = options();
        opts.mode = MODE_HC;
        opts.hc_alpha = 1.1;
        {
            let req = request(&positions, &edges, &mut output, &opts);
            assert_eq!(
                unsafe { ywta_mesh_smoothing_apply(&req) },
                STATUS_INVALID_ARGUMENT
            );
        }

        opts.hc_alpha = 0.0;
        opts.hc_beta = f64::NAN;
        let req = request(&positions, &edges, &mut output, &opts);
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_NON_FINITE
        );
    }

    #[test]
    fn ffi_rejects_invalid_constraint_inputs() {
        let positions = [0.0; 3];
        let edges: [u32; 0] = [];
        let mut output = [0.0; 3];
        let opts = options();

        let invalid_weights = [1.5];
        let mut req = request(&positions, &edges, &mut output, &opts);
        req.vertex_weights = invalid_weights.as_ptr();
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_INVALID_CONSTRAINT
        );

        let invalid_modes = [99];
        req.vertex_weights = ptr::null();
        req.constraint_modes = invalid_modes.as_ptr();
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_INVALID_CONSTRAINT
        );

        let directional_mode = [CONSTRAINT_RAIL_LINE];
        req.constraint_modes = directional_mode.as_ptr();
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_NULL_POINTER
        );

        let zero_direction = [0.0; 3];
        req.constraint_directions = zero_direction.as_ptr();
        assert_eq!(
            unsafe { ywta_mesh_smoothing_apply(&req) },
            STATUS_INVALID_CONSTRAINT
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
            vertex_weights: ptr::null(),
            constraint_modes: ptr::null(),
            constraint_directions: ptr::null(),
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
            vertex_weights: ptr::null(),
            constraint_modes: ptr::null(),
            constraint_directions: ptr::null(),
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
