// ============================================================================
// column_solver.cpp -- unified column-based solver (S2: multi-cohort).
//
// Algorithm ported from the verified chicago_latent_gp main.cpp and generalised
// to MANY cohorts: each cohort (an OD-time demand group) has its own demand,
// its own anchor, its own explicit majors, and its own fixed nonnegative atom.
// Link resources are shared (congestion couples cohorts). For a single cohort
// the code degenerates to the verified single-OD algorithm byte-for-byte.
//
// Only the network/columns/demand change between cases (spec/PROBLEM_FORMAT.md);
// the solver is invariant. build: g++ -O2 -std=c++17 -static -o column_solver.exe
// column_solver.cpp
// run:  column_solver.exe <case_dir> --mode both|full|latent [--repeats N] ...
// ============================================================================
#include <algorithm>
#include <chrono>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using Clock = std::chrono::steady_clock;
using Vec = std::vector<double>;

struct Link { double bg{}, t0{}, cap{}, alpha{}, beta{}, toll{}; };
struct Pool {
    std::vector<Link> links;
    std::vector<std::vector<int>> paths;          // column -> resource indices
    std::vector<int> col_cohort;                  // column -> cohort id
    std::vector<double> demand;                   // cohort -> demand
    std::vector<std::vector<int>> cohort_cols;    // cohort -> column ids
    int n_cohorts{};
};
struct Solution { Vec f, od_v; double obj{}, gap{}, runtime{}; int iterations{}; };
struct CRep { int anchor{}; std::vector<int> major, minor; Vec pi, atom; double mu_ref{}; bool has_atom{}; };
struct Rep { std::vector<CRep> c; };

static std::vector<std::string> split(const std::string& s, char c) {
    std::vector<std::string> out; std::stringstream ss(s); std::string item;
    while (std::getline(ss, item, c)) out.push_back(item); return out;
}

static Pool load_case(const std::string& dir) {
    Pool p;
    { std::ifstream f(dir + "/resources.csv"); if (!f) throw std::runtime_error("no resources.csv");
      std::string ln; std::getline(f, ln);
      while (std::getline(f, ln)) { auto x = split(ln, ','); if (x.size() < 7) continue;
        p.links.push_back({std::stod(x[1]), std::stod(x[2]), std::stod(x[3]), std::stod(x[4]), std::stod(x[5]), std::stod(x[6])}); } }
    { std::ifstream f(dir + "/columns.csv"); if (!f) throw std::runtime_error("no columns.csv");
      std::string ln; std::getline(f, ln);
      while (std::getline(f, ln)) { auto x = split(ln, ','); if (x.size() < 3) continue;
        int coh = std::stoi(x[1]); p.col_cohort.push_back(coh); p.n_cohorts = std::max(p.n_cohorts, coh + 1);
        std::vector<int> path; for (auto& s : split(x[2], ';')) if (!s.empty()) path.push_back(std::stoi(s));
        p.paths.push_back(std::move(path)); } }
    p.demand.assign(p.n_cohorts, 0);
    { std::ifstream f(dir + "/demand.csv"); if (!f) throw std::runtime_error("no demand.csv");
      std::string ln; std::getline(f, ln);
      while (std::getline(f, ln)) { auto x = split(ln, ','); if (x.size() < 5) continue;
        int c = std::stoi(x[0]); if (c < p.n_cohorts) p.demand[c] = std::stod(x[4]); } }
    p.cohort_cols.assign(p.n_cohorts, {});
    for (int k = 0; k < (int)p.paths.size(); ++k) p.cohort_cols[p.col_cohort[k]].push_back(k);
    return p;
}

static inline double cost(const Link& a, double v) { double r = std::max(v, 0.0) / a.cap; return a.t0 * (1.0 + a.alpha * std::pow(r, a.beta)) + a.toll; }
static inline double deriv(const Link& a, double v) { if (a.beta <= 0) return 0; double r = std::max(v, 0.0) / a.cap; return a.t0 * a.alpha * a.beta * std::pow(r, a.beta - 1.0) / a.cap; }
static double objective(const Pool& p, const Vec& odv, const std::vector<int>& sup) { double z = 0; for (int ii : sup) { auto& a = p.links[ii]; double b = a.bg, x = std::max(odv[ii], 0.0), u = b + x; z += a.t0 * x + a.toll * x + a.t0 * a.alpha / ((a.beta + 1.0) * std::pow(a.cap, a.beta)) * (std::pow(u, a.beta + 1.0) - std::pow(b, a.beta + 1.0)); } return z; }
static std::vector<int> all_support(const Pool& p) { std::vector<char> seen(p.links.size(), 0); std::vector<int> s; for (auto& path : p.paths) for (int a : path) if (!seen[a]) { seen[a] = 1; s.push_back(a); } return s; }
static void stamp(const std::vector<int>& path, double amt, Vec& v) { for (int a : path) v[a] += amt; }
static Vec path_costs(const Pool& p, const Vec& lc) { Vec pc(p.paths.size()); for (size_t k = 0; k < p.paths.size(); ++k) { double z = 0; for (int a : p.paths[k]) z += lc[a]; pc[k] = z; } return pc; }
// system relative gap = (sum f_k c_k - sum_c d_c min_{k in c} c_k) / sum f_k c_k
static double sys_gap(const Pool& p, const Vec& f, const Vec& pc) {
    double exp = std::inner_product(f.begin(), f.end(), pc.begin(), 0.0); if (exp <= 0) return 0;
    double sumMin = 0; for (int c = 0; c < p.n_cohorts; ++c) { double mn = 1e300; for (int k : p.cohort_cols[c]) mn = std::min(mn, pc[k]); sumMin += p.demand[c] * mn; }
    return std::max(0.0, (exp - sumMin) / exp);
}

static Solution full_gp(const Pool& p, double tol, int maxit) {
    int A = (int)p.links.size(), K = (int)p.paths.size(); auto sup = all_support(p);
    Vec f(K, 0), odv(A, 0), tv(A), lc(A), dl(A), dv(A);
    for (int c = 0; c < p.n_cohorts; ++c) if (!p.cohort_cols[c].empty()) f[p.cohort_cols[c][0]] = p.demand[c];
    auto st = Clock::now();
    for (int it = 0; it <= maxit; ++it) {
        for (int a : sup) odv[a] = 0; for (int k = 0; k < K; ++k) if (f[k] != 0) stamp(p.paths[k], f[k], odv);
        for (int a : sup) { tv[a] = p.links[a].bg + odv[a]; lc[a] = cost(p.links[a], tv[a]); dl[a] = deriv(p.links[a], tv[a]); }
        Vec pc = path_costs(p, lc); double g = sys_gap(p, f, pc), obj = objective(p, odv, sup);
        double el = std::chrono::duration<double>(Clock::now() - st).count();
        if (g <= tol || it == maxit) return {f, odv, obj, g, el, it};
        Vec dir(K, 0);
        for (int c = 0; c < p.n_cohorts; ++c) {                       // per-cohort pair-Newton toward its anchor
            auto& Q = p.cohort_cols[c]; if (Q.empty()) continue;
            int anchor = Q[0]; for (int k : Q) if (pc[k] < pc[anchor]) anchor = k;
            std::vector<char> inA(A, 0); double anorm = 0; for (int a : p.paths[anchor]) { inA[a] = 1; anorm += dl[a]; }
            for (int k : Q) { if (k == anchor) { dir[k] = 0; continue; } double n = 0, o = 0; for (int a : p.paths[k]) { n += dl[a]; if (inA[a]) o += dl[a]; } double den = std::max(n + anorm - 2 * o, 1e-12); dir[k] = std::max(-(pc[k] - pc[anchor]) / den, -f[k]); }
            double pos = 0; for (int k : Q) if (dir[k] > 0) pos += dir[k]; if (pos > f[anchor] && pos > 0) { double sc = f[anchor] / pos; for (int k : Q) if (dir[k] > 0) dir[k] *= sc; }
            double s = 0; for (int k : Q) if (k != anchor) s += dir[k]; dir[anchor] = -s;
        }
        for (int a : sup) dv[a] = 0; for (int k = 0; k < K; ++k) if (dir[k] != 0) stamp(p.paths[k], dir[k], dv);
        double dirc = 0; for (int a : sup) dirc += lc[a] * dv[a]; double step = 1;
        while (step > 1e-10) { Vec tr = odv; for (int a : sup) tr[a] += step * dv[a]; if (objective(p, tr, sup) <= obj + 1e-4 * step * dirc) break; step *= 0.5; }
        for (int k = 0; k < K; ++k) { f[k] += step * dir[k]; if (std::abs(f[k]) < 1e-14) f[k] = 0; }
    } throw std::runtime_error("unreachable");
}

// project the sub-vector v[idx] onto the simplex {u >= 0, sum u = d} (Duchi et al.)
static void proj_simplex_eq(Vec& v, const std::vector<int>& idx, double d) {
    int n = (int)idx.size(); if (n == 0) return;
    std::vector<double> u(n); for (int i = 0; i < n; ++i) u[i] = v[idx[i]];
    std::sort(u.begin(), u.end(), std::greater<double>());
    double cs = 0, theta = 0; for (int i = 0; i < n; ++i) { cs += u[i]; double t = (cs - d) / (i + 1.0); if (u[i] > t) theta = t; }
    for (int i = 0; i < n; ++i) v[idx[i]] = std::max(v[idx[i]] - theta, 0.0);
}

// H0: full-simplex projected gradient. All columns are free variables; demand is enforced by
// EXACT per-cohort simplex projection each step (no anchor pivot / no elimination). This is the
// non-eliminated baseline for the R/C decomposition.
static Solution h0_pgd(const Pool& p, double tol, int maxit) {
    int A = (int)p.links.size(), K = (int)p.paths.size(); auto sup = all_support(p);
    Vec x(K, 0), odv(A, 0), tv(A), lc(A), dl(A), dv(A);
    for (int c = 0; c < p.n_cohorts; ++c) { auto& Q = p.cohort_cols[c]; if (!Q.empty()) { double u = p.demand[c] / Q.size(); for (int k : Q) x[k] = u; } }
    auto st = Clock::now();
    for (int it = 0; it <= maxit; ++it) {
        for (int a : sup) odv[a] = 0; for (int k = 0; k < K; ++k) if (x[k] != 0) stamp(p.paths[k], x[k], odv);
        for (int a : sup) { tv[a] = p.links[a].bg + odv[a]; lc[a] = cost(p.links[a], tv[a]); dl[a] = deriv(p.links[a], tv[a]); }
        Vec pc = path_costs(p, lc); double g = sys_gap(p, x, pc), obj = objective(p, odv, sup);
        double el = std::chrono::duration<double>(Clock::now() - st).count();
        if (g <= tol || it == maxit) return {x, odv, obj, g, el, it};
        double L = 1e-10; for (int k = 0; k < K; ++k) { double s = 0; for (int a : p.paths[k]) s += dl[a]; L = std::max(L, s); }
        Vec prop(K); for (int k = 0; k < K; ++k) prop[k] = x[k] - pc[k] / L;
        for (int c = 0; c < p.n_cohorts; ++c) proj_simplex_eq(prop, p.cohort_cols[c], p.demand[c]);
        Vec dir(K); for (int k = 0; k < K; ++k) dir[k] = prop[k] - x[k];
        for (int a : sup) dv[a] = 0; for (int k = 0; k < K; ++k) if (dir[k] != 0) stamp(p.paths[k], dir[k], dv);
        double directional = 0; for (int a : sup) directional += lc[a] * dv[a]; double step = 1;
        while (step > 1e-10) { Vec tr = odv; for (int a : sup) tr[a] += step * dv[a]; if (objective(p, tr, sup) <= obj + 1e-4 * step * directional) break; step *= 0.5; }
        for (int k = 0; k < K; ++k) x[k] += step * dir[k];
    } throw std::runtime_error("unreachable");
}

// Method A: Augmented Lagrangian (the paper's general framework). Demand equality is kept and
// handled by multiplier + penalty; the inner problem min_{x>=0} L is solved by projected
// gradient. Transparent basic ALM (not tuned for speed) -- to confirm it solves the SAME problem
// as OD-simplex PG (h0_pgd) and reduced gradient (full_gp).
static Solution alm(const Pool& p, double tol, int maxit) {
    int A = (int)p.links.size(), K = (int)p.paths.size(); auto sup = all_support(p);
    Vec x(K, 0), odv(A, 0), tv(A), lc(A), dl(A), dv(A), lam(p.n_cohorts, 0), res(p.n_cohorts, 0);
    for (int c = 0; c < p.n_cohorts; ++c) { auto& Q = p.cohort_cols[c]; if (!Q.empty()) { double u = p.demand[c] / Q.size(); for (int k : Q) x[k] = u; } }
    double rho = 1.0, prevfeas = 1e300; auto st = Clock::now(); int it = 0;
    Vec xprev(K), gprev(K); bool hp = false;                                  // Barzilai-Borwein history
    for (int outer = 0; outer < 400 && it <= maxit; ++outer) {
        for (int inner = 0; inner < 400 && it <= maxit; ++inner, ++it) {          // inner: min_{x>=0} L by spectral (BB) projected gradient
            for (int a : sup) odv[a] = 0; for (int k = 0; k < K; ++k) if (x[k] != 0) stamp(p.paths[k], x[k], odv);
            for (int a : sup) { tv[a] = p.links[a].bg + odv[a]; lc[a] = cost(p.links[a], tv[a]); dl[a] = deriv(p.links[a], tv[a]); }
            for (int c = 0; c < p.n_cohorts; ++c) { double r = -p.demand[c]; for (int k : p.cohort_cols[c]) r += x[k]; res[c] = r; }
            Vec pc = path_costs(p, lc); double Lipc = 1e-8; for (int a : sup) Lipc = std::max(Lipc, dl[a]);
            Vec g(K); double gn = 0; for (int c = 0; c < p.n_cohorts; ++c) for (int k : p.cohort_cols[c]) { g[k] = pc[k] + lam[c] + rho * res[c]; double pgc = (x[k] > 0 || g[k] < 0) ? g[k] : 0; gn += pgc * pgc; }
            if (gn < 1e-13) break;
            double step;
            if (hp) { double sy = 0, ss = 0; for (int k = 0; k < K; ++k) { double sk = x[k] - xprev[k], yk = g[k] - gprev[k]; sy += sk * yk; ss += sk * sk; } step = (sy > 1e-30 && ss > 0) ? ss / sy : 1.0 / (Lipc + rho); if (!(step > 1e-12 && step < 1e9)) step = 1.0 / (Lipc + rho); }
            else step = 1.0 / (Lipc + rho + 1e-12);
            xprev = x; gprev = g; hp = true;
            for (int k = 0; k < K; ++k) x[k] = std::max(x[k] - step * g[k], 0.0);
        }
        double feas = 0; for (int c = 0; c < p.n_cohorts; ++c) { double r = -p.demand[c]; for (int k : p.cohort_cols[c]) r += x[k]; lam[c] += rho * r; feas = std::max(feas, std::abs(r)); }
        // feasible-projected gap
        Vec xf(x); for (int c = 0; c < p.n_cohorts; ++c) proj_simplex_eq(xf, p.cohort_cols[c], p.demand[c]);
        for (int a : sup) odv[a] = 0; for (int k = 0; k < K; ++k) if (xf[k] != 0) stamp(p.paths[k], xf[k], odv);
        for (int a : sup) { tv[a] = p.links[a].bg + odv[a]; lc[a] = cost(p.links[a], tv[a]); }
        Vec pc = path_costs(p, lc); double g = sys_gap(p, xf, pc), obj = objective(p, odv, sup);
        double el = std::chrono::duration<double>(Clock::now() - st).count();
        if ((feas < 1e-9 && g <= tol) || it >= maxit) return {xf, odv, obj, g, el, it};
        if (feas > 0.5 * prevfeas) rho = std::min(rho * 2.0, 1e7); prevfeas = feas;
    }
    Vec xf(x); for (int c = 0; c < p.n_cohorts; ++c) proj_simplex_eq(xf, p.cohort_cols[c], p.demand[c]);
    for (int a : sup) odv[a] = 0; for (int k = 0; k < K; ++k) if (xf[k] != 0) stamp(p.paths[k], xf[k], odv);
    for (int a : sup) { tv[a] = p.links[a].bg + odv[a]; lc[a] = cost(p.links[a], tv[a]); }
    Vec pc = path_costs(p, lc); return {xf, odv, objective(p, odv, sup), sys_gap(p, xf, pc), std::chrono::duration<double>(Clock::now() - st).count(), it};
}

static Rep extract_rep(const Pool& p, const Solution& s, double majorShare, double minLatent) {
    Rep R; R.c.resize(p.n_cohorts);
    for (int c = 0; c < p.n_cohorts; ++c) {
        auto& Q = p.cohort_cols[c]; double d = p.demand[c]; CRep cr;
        std::vector<int> pos; for (int k : Q) if (s.f[k] > std::max(1e-12, 1e-10 * d)) pos.push_back(k);
        // anchor = min reference-cost column among positive-flow columns (costs at the reference solution)
        int anchor = pos.empty() ? (Q.empty() ? 0 : Q[0]) : pos[0]; double best = 1e300;
        for (int k : (pos.empty() ? Q : pos)) { double z = 0; for (int a : p.paths[k]) { auto& lk = p.links[a]; z += cost(lk, lk.bg + std::max(s.od_v[a], 0.0)); } if (z < best) { best = z; anchor = k; } }
        std::vector<int> order; for (int k : Q) if (k != anchor) order.push_back(k);
        std::stable_sort(order.begin(), order.end(), [&](int a, int b) { return s.f[a] > s.f[b]; });
        double cum = s.f[anchor]; std::vector<int> maj; for (int k : order) { if (cum >= majorShare * d || s.f[k] <= 1e-14) break; maj.push_back(k); cum += s.f[k]; }
        auto buildMinor = [&]() { std::vector<char> mk(p.paths.size(), 0); mk[anchor] = 1; for (int k : maj) mk[k] = 1; std::vector<int> m; for (int k : Q) if (!mk[k]) m.push_back(k); return m; };
        auto minor = buildMinor(); auto mu_of = [&]() { double z = 0; for (int k : minor) z += s.f[k]; return z; }; double mu = mu_of();
        while (!maj.empty() && mu < minLatent * d) { auto it = std::min_element(maj.begin(), maj.end(), [&](int a, int b) { return s.f[a] < s.f[b]; }); maj.erase(it); minor = buildMinor(); mu = mu_of(); }
        cr.anchor = anchor; cr.major = maj; cr.minor = minor; cr.mu_ref = mu; cr.has_atom = (mu > 1e-14);
        if (cr.has_atom) { cr.pi.assign(minor.size(), 0); cr.atom.assign(p.links.size(), 0); for (size_t i = 0; i < minor.size(); ++i) { cr.pi[i] = s.f[minor[i]] / mu; for (int a : p.paths[minor[i]]) cr.atom[a] += cr.pi[i]; } }
        std::sort(cr.major.begin(), cr.major.end()); R.c[c] = cr;
    }
    return R;
}

// R0 rep: exact per-cohort anchor elimination, ALL non-anchor columns explicit, NO atom.
// Same anchor rule as extract_rep, so H0/R0/R1 share anchors and the decomposition is consistent.
static Rep make_r0_rep(const Pool& p, const Solution& s) {
    Rep R; R.c.resize(p.n_cohorts);
    for (int c = 0; c < p.n_cohorts; ++c) {
        auto& Q = p.cohort_cols[c]; double d = p.demand[c]; CRep cr;
        std::vector<int> pos; for (int k : Q) if (s.f[k] > std::max(1e-12, 1e-10 * d)) pos.push_back(k);
        int anchor = pos.empty() ? (Q.empty() ? 0 : Q[0]) : pos[0]; double best = 1e300;
        for (int k : (pos.empty() ? Q : pos)) { double z = 0; for (int a : p.paths[k]) { auto& lk = p.links[a]; z += cost(lk, lk.bg + std::max(s.od_v[a], 0.0)); } if (z < best) { best = z; anchor = k; } }
        cr.anchor = anchor; cr.has_atom = false; cr.mu_ref = 0;
        for (int k : Q) if (k != anchor) cr.major.push_back(k);
        std::sort(cr.major.begin(), cr.major.end()); R.c[c] = cr;
    }
    return R;
}

static Solution latent_gp(const Pool& p, const Rep& R, double tol, int maxit, int certEvery) {
    int A = (int)p.links.size(), K = (int)p.paths.size(); auto sup = all_support(p);
    // SPARSE per-cohort layout: each cohort's residuals live over its LOCAL link support only
    // (the links its columns touch), so all per-cohort work is O(local nnz), not O(all links).
    std::vector<int> Mc(p.n_cohorts);
    std::vector<std::vector<int>> loc(p.n_cohorts);          // cohort -> local global-link ids
    std::vector<std::vector<double>> ancloc(p.n_cohorts);    // anchor indicator over loc
    std::vector<std::vector<std::vector<double>>> rloc(p.n_cohorts);  // cohort -> M x |loc|
    std::vector<int> mark(A, -1), lpos(A, -1);
    for (int c = 0; c < p.n_cohorts; ++c) {
        auto& cr = R.c[c]; int M = (int)cr.major.size() + (cr.has_atom ? 1 : 0); Mc[c] = M;
        for (int k : p.cohort_cols[c]) for (int a : p.paths[k]) if (mark[a] != c) { mark[a] = c; loc[c].push_back(a); }
        int nl = (int)loc[c].size(); for (int l = 0; l < nl; ++l) lpos[loc[c][l]] = l;
        ancloc[c].assign(nl, 0); for (int a : p.paths[cr.anchor]) ancloc[c][lpos[a]] += 1;
        rloc[c].assign(M, std::vector<double>(nl, 0));
        for (size_t j = 0; j < cr.major.size(); ++j) { for (int a : p.paths[cr.major[j]]) rloc[c][j][lpos[a]] += 1; for (int l = 0; l < nl; ++l) rloc[c][j][l] -= ancloc[c][l]; }
        if (cr.has_atom) { for (size_t i = 0; i < cr.minor.size(); ++i) for (int a : p.paths[cr.minor[i]]) rloc[c][M - 1][lpos[a]] += cr.pi[i]; for (int l = 0; l < nl; ++l) rloc[c][M - 1][l] -= ancloc[c][l]; }
        for (int l = 0; l < nl; ++l) lpos[loc[c][l]] = -1;   // reset stamp
    }
    std::vector<Vec> x(p.n_cohorts); for (int c = 0; c < p.n_cohorts; ++c) x[c].assign(Mc[c], 0);
    Vec odv(A, 0), tv(A), lc(A), dl(A), dvall(A, 0), fullf(K); auto st = Clock::now();
    for (int it = 0; it <= maxit; ++it) {
        for (int a : sup) odv[a] = 0;
        for (int c = 0; c < p.n_cohorts; ++c) { int nl = (int)loc[c].size(); for (int l = 0; l < nl; ++l) { double v = p.demand[c] * ancloc[c][l]; for (int j = 0; j < Mc[c]; ++j) v += rloc[c][j][l] * x[c][j]; odv[loc[c][l]] += v; } }
        for (int a : sup) { tv[a] = p.links[a].bg + odv[a]; lc[a] = cost(p.links[a], tv[a]); dl[a] = deriv(p.links[a], tv[a]); }
        double obj = objective(p, odv, sup);
        bool cert = (it % certEvery == 0 || it == maxit);
        if (cert) { Vec pc = path_costs(p, lc); std::fill(fullf.begin(), fullf.end(), 0);
            for (int c = 0; c < p.n_cohorts; ++c) { auto& cr = R.c[c]; double sx = 0; for (double v : x[c]) sx += v; fullf[cr.anchor] = p.demand[c] - sx; for (size_t j = 0; j < cr.major.size(); ++j) fullf[cr.major[j]] = x[c][j]; if (cr.has_atom) { double mass = x[c].back(); for (size_t i = 0; i < cr.minor.size(); ++i) fullf[cr.minor[i]] = mass * cr.pi[i]; } }
            double g = sys_gap(p, fullf, pc); double el = std::chrono::duration<double>(Clock::now() - st).count();
            if (g <= tol || it == maxit) return {fullf, odv, obj, g, el, it}; }
        for (int a : sup) dvall[a] = 0; std::vector<Vec> dir(p.n_cohorts);
        for (int c = 0; c < p.n_cohorts; ++c) { int M = Mc[c]; dir[c].assign(M, 0); if (M == 0) continue; int nl = (int)loc[c].size();
            Vec grad(M); std::vector<Vec> H(M, Vec(M, 0)); for (int j = 0; j < M; ++j) { double gg = 0; for (int l = 0; l < nl; ++l) gg += rloc[c][j][l] * lc[loc[c][l]]; grad[j] = gg; for (int k = 0; k < M; ++k) { double z = 0; for (int l = 0; l < nl; ++l) z += rloc[c][j][l] * dl[loc[c][l]] * rloc[c][k][l]; H[j][k] = z; } }
            double L = 1e-10; for (int j = 0; j < M; ++j) { double rs = 0; for (int k = 0; k < M; ++k) rs += std::abs(H[j][k]); L = std::max(L, rs); }
            Vec prop(M); for (int j = 0; j < M; ++j) prop[j] = x[c][j] - grad[j] / L;
            double cap = p.demand[c]; for (double& v : prop) v = std::max(v, 0.0); double ssum = 0; for (double v : prop) ssum += v;   // project onto {u>=0, sum u <= demand}
            if (ssum > cap) { Vec u = prop; std::sort(u.begin(), u.end(), std::greater<double>()); double cs = 0, th = 0; int rho = -1; for (size_t i = 0; i < u.size(); ++i) { cs += u[i]; double t = (cs - cap) / (i + 1.0); if (u[i] - t > 0) { rho = (int)i; th = t; } } if (rho < 0) std::fill(prop.begin(), prop.end(), 0.0); else for (double& v : prop) v = std::max(v - th, 0.0); }
            for (int j = 0; j < M; ++j) { dir[c][j] = prop[j] - x[c][j]; for (int l = 0; l < nl; ++l) dvall[loc[c][l]] += rloc[c][j][l] * dir[c][j]; }
        }
        double directional = 0; for (int a : sup) directional += lc[a] * dvall[a]; double step = 1;   // ONE global line search on the aggregate direction
        while (step > 1e-10) { Vec tr = odv; for (int a : sup) tr[a] += step * dvall[a]; if (objective(p, tr, sup) <= obj + 1e-4 * step * directional) break; step *= 0.5; }
        for (int c = 0; c < p.n_cohorts; ++c) for (int j = 0; j < Mc[c]; ++j) x[c][j] += step * dir[c][j];
    } throw std::runtime_error("unreachable");
}

// ---- SVD compression model (manuscript SVD+ALM) --------------------------------------------
// one-sided Jacobi: given dense M (nr x nc, row-major), return top-k LEFT singular vectors
// U (nr x k, row-major) and singular values sv[k]. Orthogonalises columns of M (=> M V has
// orthogonal columns = U*S), then U_i = (MV)_i / sv_i. Small per-cohort blocks -> cheap.
static void jacobi_left(const std::vector<double>& M, int nr, int nc, int k,
                        std::vector<double>& U, std::vector<double>& sv) {
    std::vector<double> W(M);   // nr x nc, will become M*V
    for (int sweep = 0; sweep < 30; ++sweep) {
        double off = 0;
        for (int p = 0; p < nc; ++p) for (int q = p + 1; q < nc; ++q) {
            double a = 0, b = 0, cdot = 0;
            for (int i = 0; i < nr; ++i) { double wp = W[i * nc + p], wq = W[i * nc + q]; a += wp * wp; b += wq * wq; cdot += wp * wq; }
            if (std::abs(cdot) < 1e-14 * std::sqrt(a * b + 1e-300)) continue; off += cdot * cdot;
            double zeta = (b - a) / (2 * cdot), t = (zeta > 0 ? 1 : -1) / (std::abs(zeta) + std::sqrt(1 + zeta * zeta));
            double cc = 1 / std::sqrt(1 + t * t), ss = cc * t;
            for (int i = 0; i < nr; ++i) { double wp = W[i * nc + p], wq = W[i * nc + q]; W[i * nc + p] = cc * wp - ss * wq; W[i * nc + q] = ss * wp + cc * wq; }
        }
        if (off < 1e-18) break;
    }
    std::vector<std::pair<double, int>> nrm(nc);
    for (int j = 0; j < nc; ++j) { double s = 0; for (int i = 0; i < nr; ++i) s += W[i * nc + j] * W[i * nc + j]; nrm[j] = {std::sqrt(s), j}; }
    std::sort(nrm.begin(), nrm.end(), std::greater<std::pair<double, int>>());
    int kk = std::min(k, nc); U.assign((size_t)nr * kk, 0); sv.assign(kk, 0);
    for (int c = 0; c < kk; ++c) { int j = nrm[c].second; double s = nrm[c].first; sv[c] = s; if (s < 1e-12) continue; for (int i = 0; i < nr; ++i) U[i * kk + c] = W[i * nc + j] / s; }
}

// R1_svd: anchor elimination + truncated-SVD minor compression, U_r z >= 0 + demand by ALM
// penalties (penalty method). Per cohort: explicit majors y>=0, SVD coords z (free); anchor
// eliminated. Reduced gradient on (y,z) with quadratic penalties; feasible objective reported
// at a projected point for a matched-accuracy gap. rank = per-cohort SVD truncation.
static Solution svd_gp(const Pool& p, const Rep& R, int rank, double tol, int maxit) {
    int A = (int)p.links.size(), K = (int)p.paths.size(); auto sup = all_support(p);
    std::vector<std::vector<int>> loc(p.n_cohorts); std::vector<std::vector<double>> ancl(p.n_cohorts);
    std::vector<std::vector<std::vector<double>>> Rmaj(p.n_cohorts);   // per cohort: nmaj x |loc|
    std::vector<std::vector<double>> Ur(p.n_cohorts), Dc(p.n_cohorts), Uone(p.n_cohorts); // U:nmin x r ; D:|loc| x r ; Uone: r
    std::vector<int> rc(p.n_cohorts), nminc(p.n_cohorts);
    std::vector<int> mk(A, -1), lp(A, -1);
    for (int c = 0; c < p.n_cohorts; ++c) {
        auto& cr = R.c[c]; for (int kk : p.cohort_cols[c]) for (int a : p.paths[kk]) if (mk[a] != c) { mk[a] = c; loc[c].push_back(a); }
        int nl = (int)loc[c].size(); for (int l = 0; l < nl; ++l) lp[loc[c][l]] = l;
        ancl[c].assign(nl, 0); for (int a : p.paths[cr.anchor]) ancl[c][lp[a]] += 1;
        Rmaj[c].assign(cr.major.size(), std::vector<double>(nl, 0));
        for (size_t j = 0; j < cr.major.size(); ++j) { for (int a : p.paths[cr.major[j]]) Rmaj[c][j][lp[a]] += 1; for (int l = 0; l < nl; ++l) Rmaj[c][j][l] -= ancl[c][l]; }
        int nmin = (int)cr.minor.size(); nminc[c] = nmin;
        if (nmin > 0) {
            std::vector<double> Mden((size_t)nmin * nl, 0);      // minor reduced block (nmin x |loc|)
            for (int i = 0; i < nmin; ++i) { for (int a : p.paths[cr.minor[i]]) Mden[(size_t)i * nl + lp[a]] += 1; for (int l = 0; l < nl; ++l) Mden[(size_t)i * nl + l] -= ancl[c][l]; }
            std::vector<double> sv; int r = std::min(rank, std::min(nmin, nl)); jacobi_left(Mden, nmin, nl, r, Ur[c], sv); rc[c] = r;
            // Dc = Mden' * Ur (|loc| x r); Uone = Ur' * 1 (r)
            Dc[c].assign((size_t)nl * r, 0); Uone[c].assign(r, 0);
            for (int i = 0; i < nmin; ++i) for (int cc = 0; cc < r; ++cc) { double u = Ur[c][(size_t)i * r + cc]; Uone[c][cc] += u; for (int l = 0; l < nl; ++l) Dc[c][(size_t)l * r + cc] += Mden[(size_t)i * nl + l] * u; }
        } else rc[c] = 0;
        for (int l = 0; l < nl; ++l) lp[loc[c][l]] = -1;
    }
    std::vector<std::vector<double>> y(p.n_cohorts), z(p.n_cohorts);
    for (int c = 0; c < p.n_cohorts; ++c) { y[c].assign(R.c[c].major.size(), 0); z[c].assign(rc[c], 0); }
    Vec odv(A, 0), tv(A), lc(A), dl(A), fullf(K); double rho = 1.0; auto st = Clock::now();
    for (int it = 0; it <= maxit; ++it) {
        for (int a : sup) odv[a] = 0;
        for (int c = 0; c < p.n_cohorts; ++c) { int nl = (int)loc[c].size(); for (int l = 0; l < nl; ++l) { double v = p.demand[c] * ancl[c][l]; for (size_t j = 0; j < y[c].size(); ++j) v += Rmaj[c][j][l] * y[c][j]; for (int cc = 0; cc < rc[c]; ++cc) v += Dc[c][(size_t)l * rc[c] + cc] * z[c][cc]; odv[loc[c][l]] += v; } }
        for (int a : sup) { tv[a] = p.links[a].bg + odv[a]; lc[a] = cost(p.links[a], tv[a]); dl[a] = deriv(p.links[a], tv[a]); }
        // feasible-projected gap: clip minor flows to >=0, rescale each cohort to demand, price
        if (it % 10 == 0 || it == maxit) {
            std::fill(fullf.begin(), fullf.end(), 0);
            for (int c = 0; c < p.n_cohorts; ++c) { auto& cr = R.c[c]; double s = 0; for (size_t j = 0; j < cr.major.size(); ++j) { fullf[cr.major[j]] = std::max(y[c][j], 0.0); s += fullf[cr.major[j]]; }
                for (int i = 0; i < nminc[c]; ++i) { double w = 0; for (int cc = 0; cc < rc[c]; ++cc) w += Ur[c][(size_t)i * rc[c] + cc] * z[c][cc]; w = std::max(w, 0.0); fullf[cr.minor[i]] = w; s += w; }
                double sc = (s > 1e-12) ? p.demand[c] / s : 0; if (s <= 1e-12) { fullf[cr.anchor] = p.demand[c]; continue; }
                for (size_t j = 0; j < cr.major.size(); ++j) fullf[cr.major[j]] *= sc; for (int i = 0; i < nminc[c]; ++i) fullf[cr.minor[i]] *= sc; fullf[cr.anchor] = 0; }
            Vec vv(A, 0); for (int k = 0; k < K; ++k) if (fullf[k] != 0) stamp(p.paths[k], fullf[k], vv);
            for (int a : sup) vv[a] += p.links[a].bg; Vec lcf(A); for (int a : sup) lcf[a] = cost(p.links[a], vv[a]);
            Vec pc = path_costs(p, lcf); double g = sys_gap(p, fullf, pc);
            double obj = 0; for (int a : sup) { double b = p.links[a].bg, x = std::max(vv[a] - b, 0.0), u = b + x; auto& lk = p.links[a]; obj += lk.t0 * x + lk.toll * x + lk.t0 * lk.alpha / ((lk.beta + 1) * std::pow(lk.cap, lk.beta)) * (std::pow(u, lk.beta + 1) - std::pow(b, lk.beta + 1)); }
            double el = std::chrono::duration<double>(Clock::now() - st).count();
            if (g <= tol || it == maxit) return {fullf, odv, obj, g, el, it};
        }
        // penalized objective L(y,z) = Beckmann(odv) + (rho/2)[ sum min(w,0)^2 + capviol^2 ]
        auto Lpen = [&](const std::vector<std::vector<double>>& yy, const std::vector<std::vector<double>>& zz) {
            for (int a : sup) odv[a] = 0; double pen = 0;
            for (int c = 0; c < p.n_cohorts; ++c) { int nl = (int)loc[c].size(), r = rc[c]; double mass = 0;
                for (int l = 0; l < nl; ++l) { double v = p.demand[c] * ancl[c][l]; for (size_t j = 0; j < yy[c].size(); ++j) v += Rmaj[c][j][l] * yy[c][j]; for (int cc = 0; cc < r; ++cc) v += Dc[c][(size_t)l * r + cc] * zz[c][cc]; odv[loc[c][l]] += v; }
                for (size_t j = 0; j < yy[c].size(); ++j) mass += yy[c][j];
                for (int i = 0; i < nminc[c]; ++i) { double w = 0; for (int cc = 0; cc < r; ++cc) w += Ur[c][(size_t)i * r + cc] * zz[c][cc]; mass += w; if (w < 0) pen += w * w; }
                double cv = std::max(mass - p.demand[c], 0.0); pen += cv * cv; }
            return objective(p, odv, sup) + 0.5 * rho * pen; };
        double L0 = Lpen(y, z);
        double sc = 1e-8; for (int a : sup) sc = std::max(sc, dl[a]); sc = 1.0 / (sc * 20 + rho);   // step scale
        std::vector<std::vector<double>> yn(y), zn(z);
        for (int c = 0; c < p.n_cohorts; ++c) { int nl = (int)loc[c].size(), r = rc[c]; double mass = 0; for (double v : y[c]) mass += v;
            std::vector<double> w(nminc[c], 0); for (int i = 0; i < nminc[c]; ++i) { double v = 0; for (int cc = 0; cc < r; ++cc) v += Ur[c][(size_t)i * r + cc] * z[c][cc]; w[i] = v; mass += v; }
            double cv = std::max(mass - p.demand[c], 0.0);
            for (size_t j = 0; j < y[c].size(); ++j) { double g = 0; for (int l = 0; l < nl; ++l) g += Rmaj[c][j][l] * lc[loc[c][l]]; g += rho * cv; yn[c][j] = g; }
            for (int cc = 0; cc < r; ++cc) { double g = 0; for (int l = 0; l < nl; ++l) g += Dc[c][(size_t)l * r + cc] * lc[loc[c][l]]; for (int i = 0; i < nminc[c]; ++i) if (w[i] < 0) g += rho * w[i] * Ur[c][(size_t)i * r + cc]; g += rho * cv * Uone[c][cc]; zn[c][cc] = g; } }
        double step = sc; std::vector<std::vector<double>> yt(y), zt(z); bool ok = false;
        for (int bt = 0; bt < 30; ++bt) { for (int c = 0; c < p.n_cohorts; ++c) { for (size_t j = 0; j < y[c].size(); ++j) yt[c][j] = std::max(y[c][j] - step * yn[c][j], 0.0); for (int cc = 0; cc < rc[c]; ++cc) zt[c][cc] = z[c][cc] - step * zn[c][cc]; }
            if (Lpen(yt, zt) <= L0 + 1e-12) { ok = true; break; } step *= 0.5; }
        if (ok) { y = yt; z = zt; } else { rho = std::min(rho * 2.0, 1e8); }   // escalate rho only when stuck
    } throw std::runtime_error("unreachable");
}

static double median(std::vector<double> v) { std::sort(v.begin(), v.end()); size_t n = v.size(); return n % 2 ? v[n / 2] : 0.5 * (v[n / 2 - 1] + v[n / 2]); }

int main(int argc, char** argv) {
    try {
        if (argc < 2) { std::cerr << "usage: column_solver <case_dir> [--mode both|full|latent] [--repeats N] [--tol t] [--major-share s] [--output f]\n"; return 1; }
        std::string dir = argv[1], mode = "both", out = "", flows_out = ""; int repeats = 200, rank = 5; double tol = 1e-5, majorShare = 0.75; bool do_svd = false;
        for (int i = 2; i < argc; ++i) { std::string a = argv[i]; if (a == "--mode") mode = argv[++i]; else if (a == "--repeats") repeats = std::stoi(argv[++i]); else if (a == "--tol") tol = std::stod(argv[++i]); else if (a == "--major-share") majorShare = std::stod(argv[++i]); else if (a == "--rank") rank = std::stoi(argv[++i]); else if (a == "--svd") do_svd = true; else if (a == "--output") out = argv[++i]; else if (a == "--flows-out") flows_out = argv[++i]; }
        Pool p = load_case(dir); int K = (int)p.paths.size();
        auto ref = full_gp(p, 1e-9, 50000); auto rep = extract_rep(p, ref, majorShare, 0.05);
        int nmaj = 0, nmin = 0; double mu = 0, dem = 0; for (int c = 0; c < p.n_cohorts; ++c) { nmaj += (int)rep.c[c].major.size(); nmin += (int)rep.c[c].minor.size(); mu += rep.c[c].mu_ref; dem += p.demand[c]; }
        if (mode == "align") {   // confirm ALM / OD-simplex PG / reduced gradient solve the SAME problem
            auto stat = [&](const Solution& s) { double dres = 0, minf = 1e300; for (int c = 0; c < p.n_cohorts; ++c) { double r = -p.demand[c]; for (int k : p.cohort_cols[c]) { r += s.f[k]; minf = std::min(minf, s.f[k]); } dres = std::max(dres, std::abs(r)); } return std::make_pair(dres, minf); };
            Solution A = alm(p, tol, 200000), P = h0_pgd(p, tol, 200000), G = full_gp(p, tol, 200000);
            auto sA = stat(A), sP = stat(P), sG = stat(G); double base = std::max(std::abs(A.obj), 1e-30);
            std::cout << std::setprecision(10) << "ALIGN case=" << dir << " cohorts=" << p.n_cohorts << " K=" << K << "\n";
            std::cout << "  ALM  obj=" << A.obj << " gap=" << A.gap << " demand_res=" << sA.first << " min_flow=" << sP.second << " iters=" << A.iterations << " t=" << A.runtime << "s\n";
            std::cout << "  PG   obj=" << P.obj << " gap=" << P.gap << " demand_res=" << sP.first << " min_flow=" << sP.second << " iters=" << P.iterations << " t=" << P.runtime << "s\n";
            std::cout << "  RG   obj=" << G.obj << " gap=" << G.gap << " demand_res=" << sG.first << " min_flow=" << sG.second << " iters=" << G.iterations << " t=" << G.runtime << "s\n";
            std::cout << "  obj rel-diff:  PG-vs-ALM=" << std::abs(P.obj - A.obj) / base << "  RG-vs-ALM=" << std::abs(G.obj - A.obj) / base << "  (should be ~0)\n";
            return 0;
        }
        if (mode == "decomp") {   // H0 (full-simplex, no elim) / R0 (full_gp, elim) / R1 (latent, elim+comp)
            std::vector<double> th, tr, tl; Solution sh, sr0, sr1;
            for (int r = 0; r < repeats; ++r) { sh = h0_pgd(p, tol, 50000); th.push_back(sh.runtime); } double mH = median(th);
            for (int r = 0; r < repeats; ++r) { sr0 = full_gp(p, tol, 50000); tr.push_back(sr0.runtime); } double mR0 = median(tr);
            for (int r = 0; r < repeats; ++r) { sr1 = latent_gp(p, rep, tol, 50000, 10); tl.push_back(sr1.runtime); } double mR1 = median(tl);
            std::vector<double> ts; Solution ss; double mSVD = -1, oeSVD = -1, gapSVD = -1;
            if (do_svd) { try { int nr = std::min(repeats, 3); for (int r = 0; r < nr; ++r) { ss = svd_gp(p, rep, rank, tol, 50000); ts.push_back(ss.runtime); } mSVD = median(ts); oeSVD = std::abs(ss.obj - sh.obj) / std::max(std::abs(sh.obj), 1e-30); gapSVD = ss.gap; } catch (...) {} }
            double oeR0 = std::abs(sr0.obj - sh.obj) / std::max(std::abs(sh.obj), 1e-30);
            double oeR1 = std::abs(sr1.obj - sh.obj) / std::max(std::abs(sh.obj), 1e-30);
            std::cout << std::setprecision(6) << "DECOMP case=" << dir << " cohorts=" << p.n_cohorts << " K=" << K
                      << " majors(R1)=" << nmaj << " latent_share=" << (dem > 0 ? mu / dem : 0) << " rank=" << rank
                      << " | H0=" << mH << "s R0=" << mR0 << "s R1atom=" << mR1 << "s R1svd=" << mSVD << "s"
                      << " | S_R=" << mH / mR0 << " S_C|R_atom=" << mR0 / mR1 << " S_RC_atom=" << mH / mR1
                      << " S_C|R_svd=" << (mSVD > 0 ? mR0 / mSVD : -1) << " S_RC_svd=" << (mSVD > 0 ? mH / mSVD : -1)
                      << " | oe_R0=" << oeR0 << " oe_R1atom=" << oeR1 << " oe_R1svd=" << oeSVD
                      << " | gap_H0=" << sh.gap << " gap_R1atom=" << sr1.gap << " gap_R1svd=" << gapSVD << "\n";
            return 0;
        }
        double mf = -1, ml = -1; Solution sf, sl;
        if (mode == "both" || mode == "full") { std::vector<double> t; for (int r = 0; r < repeats; ++r) { sf = full_gp(p, tol, 50000); t.push_back(sf.runtime); } mf = median(t); }
        if (mode == "both" || mode == "latent") { std::vector<double> t; for (int r = 0; r < repeats; ++r) { sl = latent_gp(p, rep, tol, 50000, 10); t.push_back(sl.runtime); } ml = median(t); }
        double l1 = 0, den = 0, oe = 0; if (mode == "both") { for (size_t a = 0; a < sf.od_v.size(); ++a) { l1 += std::abs(sl.od_v[a] - sf.od_v[a]); den += std::abs(sf.od_v[a]); } oe = std::abs(sl.obj - sf.obj) / std::max(std::abs(sf.obj), 1e-30); }
        double sp = (mf > 0 && ml > 0) ? mf / ml : -1;
        if (!flows_out.empty()) {
            const Solution& S = (mode == "full") ? sf : sl;
            std::ofstream ff(flows_out); ff << std::setprecision(12) << "resource_id,flow" << std::endl;
            for (size_t a = 0; a < S.od_v.size(); ++a) ff << a << "," << S.od_v[a] << std::endl;
        }
        std::cout << std::setprecision(12) << "case=" << dir << " cohorts=" << p.n_cohorts << " K=" << K << " majors=" << nmaj << " latent_share=" << (dem > 0 ? mu / dem : 0) << " speedup=" << sp << " full=" << mf << " latent=" << ml << " obj_rel_err=" << oe << " full_gap=" << (mf > 0 ? sf.gap : -1) << " latent_gap=" << (ml > 0 ? sl.gap : -1) << "\n";
        if (!out.empty()) { std::ofstream f(out); f << std::setprecision(12) << "metric,value\nn_cohorts," << p.n_cohorts << "\nn_columns," << K << "\nn_major," << nmaj << "\nn_minor," << nmin << "\nlatent_share," << (dem > 0 ? mu / dem : 0) << "\nfull_gp_s," << mf << "\nlatent_gp_s," << ml << "\nspeedup," << sp << "\nfull_gap," << (mf > 0 ? sf.gap : -1) << "\nlatent_gap," << (ml > 0 ? sl.gap : -1) << "\nlink_l1_rel," << (den > 0 ? l1 / den : -1) << "\nobjective_rel_error," << oe << "\n"; }
        return 0;
    } catch (const std::exception& e) { std::cerr << "ERROR: " << e.what() << "\n"; return 1; }
}
