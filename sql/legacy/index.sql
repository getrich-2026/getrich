CREATE INDEX idx_signals_strategy    ON signals(strategy_id, published_at DESC);
CREATE INDEX idx_signals_access      ON signals(access_tier, published_at);
CREATE INDEX idx_articles_author     ON articles(author_id, published_at DESC);
CREATE INDEX idx_memberships_user    ON user_memberships(user_id, expires_at);
CREATE INDEX idx_grants_user         ON strategy_access_grants(user_id);
CREATE INDEX idx_orders_user         ON orders(user_id, created_at DESC);
CREATE INDEX idx_comments_article ON article_comments(article_id, created_at DESC);
CREATE INDEX idx_comments_parent  ON article_comments(parent_id) WHERE parent_id IS NOT NULL;