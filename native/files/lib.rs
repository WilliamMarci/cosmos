//! Cosmos ABI around the unmodified Yazi natural-sort source.
mod natsort;

#[unsafe(no_mangle)]
pub unsafe extern "C" fn cosmos_natsort(a: *const u8, an: usize, b: *const u8, bn: usize) -> i32 {
    if a.is_null() || b.is_null() { return 0; }
    let left = unsafe { std::slice::from_raw_parts(a, an) };
    let right = unsafe { std::slice::from_raw_parts(b, bn) };
    match natsort::natsort(left, right, true) {
        std::cmp::Ordering::Less => -1,
        std::cmp::Ordering::Equal => 0,
        std::cmp::Ordering::Greater => 1,
    }
}
