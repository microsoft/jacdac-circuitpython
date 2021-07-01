const fs = require("fs")
const inp = fs.readFileSync(0, "utf-8")

const repl = {
    "&&": " and ",
    "||": " or ",
    "null": "None",
    "this": "self",
    "true": "True",
    "false": "False",
    "push": "append",
    "removeElement": "remove",
    "function": "def",
}

function snakify(s) {
    const up = s.toUpperCase()
    const lo = s.toLowerCase()

    // if the name is all lowercase or all upper case don't do anything
    if (s == up || s == lo)
        return s

    // if the name already has underscores (not as first character), leave it alone
    if (s.lastIndexOf("_") > 0)
        return s

    const isUpper = (i) => s[i] != lo[i]
    const isLower = (i) => s[i] != up[i]
    //const isDigit = (i: number) => /\d/.test(s[i])

    let r = ""
    let i = 0
    while (i < s.length) {
        let upperMode = isUpper(i)
        let j = i
        while (j < s.length) {
            if (upperMode && isLower(j)) {
                // ABCd -> AB_Cd
                if (j - i > 2) {
                    j--
                    break
                } else {
                    // ABdefQ -> ABdef_Q
                    upperMode = false
                }
            }
            // abcdE -> abcd_E
            if (!upperMode && isUpper(j)) {
                break
            }
            j++
        }
        if (r) r += "_"
        r += s.slice(i, j)
        i = j
    }

    // If the name is is all caps (like a constant), preserve it
    if (r.toUpperCase() === r) {
        return r;
    }
    return r.toLowerCase();
}

const repltrg = Object.values(repl)
const replsrc = Object.keys(repl).map(k => /[a-z]/i.test(k) ?
    new RegExp("\\b" + k + "\\b", "g") :
    new RegExp(" \\" + k.split("").join("\\") + " ", "g"))


let outp = ""
for (let line of inp.split(/\r?\n/)) {
    const line0 = line
    line = line.replace(/\s*$/, "")
    let cmt = ""
    let m = /(.*?)(\s*)\/\/(.*)/.exec(line)
    if (m) {
        line = m[1]
        cmt = m[2] + "#" + m[3]
    }
    if (/^\s*}$/.test(line)) {
        if (!cmt) continue
        line = ""
    }
    for (let i = 0; i < repltrg.length; ++i)
        line = line.replace(replsrc[i], repltrg[i])
    line = line.replace(/(!+)([\(a-z])/g, (_, n, c) => n.replace(/!/g, "not ") + c)
    line = line.replace(/\bif \((.*)\) (return.*)/, (_, c, b) => "if " + c + ": " + b)
    line = line.replace(/} else/, "else")
    line = line.replace(/\belse if\b/, "elif")
    line = line.replace(/^(\s*)(const|let)\s+/, (_, w, cc) => w)
    line = line.replace(/\bemit\(\b/g, "emit(EV_")
    line = line.replace(/\s*{$/, ":")
    line = line.replace(/^(\s*)(elif|if|while) \((.*)\)\s*:$/, (_, w, kw, cond) => w + kw + " " + cond + ":")
    line = line.replace(/(\w+)/g, f => {
        if (f.toLowerCase() != f && f[0].toLowerCase() == f[0]) {
            return snakify(f)
        }
        return f
    })

    for (const op of Object.keys(repl)) {
        line = line.split(op).join(repl[op])
    }

    line += cmt
    //console.log(line0)
    console.log(line)
}
