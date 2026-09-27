args <- commandArgs(TRUE); ubi <- args[1]; nsamp <- as.integer(args[2]); thin <- as.integer(args[3]); burn <- as.integer(args[4])
.libPaths(c(file.path(getwd(),'rlib'), .libPaths())); suppressMessages(library(eiPack))
x <- read.csv(sprintf('ei_in_%s.csv', ubi))
pr <- grep('^p_', names(x), value=TRUE); dc <- grep('^d_', names(x), value=TRUE)
f <- as.formula(sprintf('cbind(%s) ~ cbind(%s)', paste(dc, collapse=','), paste(pr, collapse=',')))
seed <- as.integer(args[5]); set.seed(seed); t0 <- Sys.time()
fit <- ei.MD.bayes(f, data=x, sample=nsamp, thin=thin, burnin=burn, ret.beta='r', ret.mcmc=TRUE, verbose=0)
lam <- lambda.MD(fit, dc)   # draws x (r*c): P(dist | prov) agregado sobre mesas
cat(format(Sys.time()-t0), '\n')
saveRDS(list(lam=lam, alpha=fit$draws$Alpha), sprintf('ei_md_%s_%d.rds', ubi, seed))
write.csv(as.data.frame(as.matrix(lam)), sprintf('ei_lambda_%s_%d.csv', ubi, seed), row.names=FALSE)
# convergencia en alpha
suppressMessages(library(coda)); g <- geweke.diag(fit$draws$Alpha)$z; cat('geweke |z|>2:', mean(abs(g)>2, na.rm=TRUE), '\n')
