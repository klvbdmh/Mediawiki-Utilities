from itertools import chain

from ...types import Timestamp
from ...util import none_or

from .functions import detect

"""
Simple constant used in order to not do weird things with a dummy revision.
"""
def check_row(db, rev_row, **kwargs):
	"""
	Checks whether a revision (database row) was reverted (identity) and returns 
	a named tuple of Revert(reverting, reverteds, reverted_to).
	
	:Parameters:
		db : `mw.database.DB` 
		rev_row : dict
			a revision row containing a 'rev_sha1' and a 'rev_page' or 'page_id'
		radius : int
			the maximum number of revisions that can be reverted
		check_archive : bool
			should the archive table be check for reverting revisions?
		before : `Timestamp`
			if set, limits the search for *reverting* revisions to those which were saved before this timestamp
	"""
	
	# extract rev_id, sha1, page_id
	if 'rev_id' in rev_row: rev_id = rev_row['rev_id']
	else: raise TypeError("rev_row must have 'rev_id'")
	if 'rev_sha1' in rev_row: sha1 = rev_row['rev_sha1']
	else: raise TypeError("rev_row must have 'rev_sha1'")
	if 'page_id' in rev_row: page_id = rev_row['page_id']
	elif 'rev_page' in rev_row: page_id = rev_row['rev_page']
	else: raise TypeError("rev_row must have 'page_id' or 'rev_page'")
	
	# run the regular check
	return check(db, rev_id, sha1=sha1, page_id=page_id, **kwargs)
	


def check(db, rev_id, sha1=None, page_id=None, radius=15, check_archive=False, before=None):
	"""
	Checks whether a revision was reverted (identity) and returns a named tuple
	of Revert(reverting, reverteds, reverted_to).
	
	:Parameters:
		db : `mw.database.DB` 
		rev_id : int
			the ID of the revision to check
		sha1 : str
			a sha1 checksum of the revision text (slower if not provided)
		page_id : int
			the ID of the page the revision occupies (slower if not provided)
		radius : int
			the maximum number of revisions that can be reverted
		check_archive : bool
			should the archive table be check for reverting revisions?
		before : `Timestamp`
			if set, limits the search for *reverting* revisions to those which were saved before this timestamp
	"""
	
	if not hasattr(db, "revisions") and hasattr(db, "all_revisions"):
		raise TypeError("db wrong type.  Expected a mw.database.DB.")
	
	rev_id = int(rev_id)
	radius = int(radius)
	sha1 = none_or(sha1, str)
	page_id = none_or(page_id, int)
	check_archive = bool(check_archive)
	before = none_or(before, Timestamp)
	
	# If we are searching the archive, we'll need to use `all_revisions`.
	if check_archive: dbrevs = db.all_revisions
	else: dbrevs = db.revisions
	
	# If we don't have the sha1 or page_id, we're going to need to look them up
	if sha1 == None or page_id == None:
		row = dbrevs.get(id=rev_id)
		sha1 = row['sha1']
		page_id = row['rev_page']
		
	# Load history and current rev
	current_and_past_revs = list(dbrevs.query(
		page_id=page_id,
		limit=radius+1,
		before_id=rev_id+1, # Ensures that we capture the current revision
		direction="older"
	))
	
	try:
		# Extract current rev and reorder history
		current_rev, past_revs = (
			current_and_past_revs[0], # Current rev is the first one returned
			reversed(current_and_past_revs[1:]) # The rest are past revs, but they are in the wrong order
		)
	except IndexError:
		# Only way to get here is if there isn't enough history.  Couldn't be 
		# reverted.  Just return None. 
		return None
	
	# Load future revisions
	future_revs = dbrevs.query(
		page_id=page_id,
		limit=radius,
		after_id=rev_id,
		before=before,
		direction="newer"
	)
	
	# Convert to an iterable of (checksum, rev) pairs for detect() to consume
	checksum_revisions = chain(
		((rev['rev_sha1'], rev) for rev in past_revs),
		[(sha1, current_rev)],
		((rev['rev_sha1'], rev) for rev in future_revs)
	)
	
	for revert in detect(checksum_revisions, radius=radius):
		# Check that this is a relevant revert
		if rev_id in [rev['rev_id'] for rev in revert.reverteds]:
			return revert
		
	return None