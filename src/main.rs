use chrono;
use std::env;

fn main() {
    // First task: when the user calls "diary", I want neovim to open the diary entry of the
    // current day. If it doesn't exist, do we have to "touch" it first? Go to start of new line.
    //
    // Need functionality so that I can retrieve all commands in my diary, sorted by date. I can
    // regenerate this file whenever I call it. Perhaps overengineered, but I could keep a json
    // file filled with the diary entries (cmd, descr, date), and the most recent parsed journal.
    // Make sure to re-parse the latest day incase we added more cmds to journal that day.
    // Then whenever I call for this cmd list, I parse the new entries, and print the cmds to
    // stdout. Also want to give functionality to print out cmds from last n days, or range of
    // days, years etc.
    //
    // Start with being able to edit journal entry
    let args: Vec<String> = env::args().collect();
    if args.len() != 1 {
        println!("Right now we don't accept any args");
    }
    // Next need dir for where to open diary. Let's do current dir + "/entries"
    let mut path_buf = env::current_dir().unwrap();
    path_buf.push("entries");
    path_buf.push(chrono::offset::Local::now().date_naive().to_string());
    path_buf.set_extension("txt");
    let path = path_buf.into_os_string().into_string().unwrap();
    println!("Full path: {}", path);
}
