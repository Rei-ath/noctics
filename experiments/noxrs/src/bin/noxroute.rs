use std::io::{self, Read};

#[path = "../neuroute.rs"]
mod neuroute;
#[path = "../routing_weights.rs"]
mod routing_weights;

fn main() -> io::Result<()> {
    let input = read_input()?;
    if input.trim().is_empty() {
        eprintln!("usage: noxroute \"1.2,0.5,3.4,-1.0\"");
        return Ok(());
    }

    let values = parse_values(&input);
    if values.is_empty() {
        eprintln!("noxroute: no values parsed");
        return Ok(());
    }

    let result = neuroute::route_values(&values);
    let mut selected = Vec::new();
    let mut rest = Vec::new();
    for (idx, &v) in values.iter().enumerate() {
        if result.mask[idx] {
            selected.push(v);
        } else {
            rest.push(v);
        }
    }

    println!("input: {:?}", values);
    println!(
        "probs: [{}]",
        result
            .probs
            .iter()
            .map(|v| format!("{v:.3}"))
            .collect::<Vec<_>>()
            .join(", ")
    );
    println!(
        "mask:  [{}]",
        result
            .mask
            .iter()
            .map(|v| if *v { "1" } else { "0" })
            .collect::<Vec<_>>()
            .join(", ")
    );
    println!("perm:  {:?}", result.perm);
    println!("selected+rest: {:?}", [selected, rest].concat());

    Ok(())
}

fn read_input() -> io::Result<String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|v| v == "-h" || v == "--help") {
        return Ok(String::new());
    }
    if !args.is_empty() {
        return Ok(args.join(" "));
    }
    let mut buf = String::new();
    io::stdin().read_to_string(&mut buf)?;
    Ok(buf)
}

fn parse_values(input: &str) -> Vec<f32> {
    input
        .replace(',', " ")
        .split_whitespace()
        .filter_map(|v| v.parse::<f32>().ok())
        .collect()
}
